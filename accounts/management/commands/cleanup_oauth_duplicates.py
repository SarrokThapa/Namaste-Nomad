from django.apps import apps
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Count
from django.db.models.functions import Lower

from social_django.models import UserSocialAuth

from accounts.models import AdminProfile, TravelerProfile, User, VendorProfile


class Command(BaseCommand):
    help = (
        "Merge duplicate users by email, relink Google OAuth records to the primary user, "
        "and remove duplicate OAuth-created accounts."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--email",
            dest="email",
            default="",
            help="Only process one email (case-insensitive).",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Apply changes. Without this flag the command runs in dry-run mode.",
        )

    def handle(self, *args, **options):
        selected_email = (options.get("email") or "").strip().lower()
        apply_changes = bool(options.get("apply"))

        duplicate_emails = self._duplicate_emails()
        if selected_email:
            duplicate_emails = [email for email in duplicate_emails if email == selected_email]

        if not duplicate_emails:
            self.stdout.write(self.style.SUCCESS("No duplicate email groups found."))
            return

        mode_label = "APPLY" if apply_changes else "DRY-RUN"
        self.stdout.write(self.style.WARNING(f"Running duplicate cleanup in {mode_label} mode."))

        processed_groups = 0
        deleted_users = 0
        moved_social = 0

        for email in duplicate_emails:
            users = list(User.objects.filter(email__iexact=email).order_by("date_joined", "id"))
            if len(users) < 2:
                continue

            if any(user.is_superuser or user.is_staff or user.user_type == "admin" for user in users):
                self.stdout.write(
                    self.style.WARNING(
                        f"Skipping {email}: group contains admin/staff/superuser account(s)."
                    )
                )
                continue

            processed_groups += 1
            primary_user = self._choose_primary_user(users)
            duplicate_users = [u for u in users if u.id != primary_user.id]

            self.stdout.write(f"Email group: {email}")
            self.stdout.write(f"Primary user: id={primary_user.id}, username={primary_user.username}")
            self.stdout.write(
                "Duplicate users: "
                + ", ".join(f"id={dup.id}, username={dup.username}" for dup in duplicate_users)
            )

            for duplicate_user in duplicate_users:
                if not apply_changes:
                    self.stdout.write(
                        f"  DRY-RUN: would relink social auth and merge related records from user {duplicate_user.id}."
                    )
                    deleted_users += 1
                    continue

                social_count = self._merge_one_duplicate(primary_user, duplicate_user)
                moved_social += social_count
                deleted_users += 1

        self.stdout.write(self.style.SUCCESS("Duplicate cleanup finished."))
        self.stdout.write(
            f"Processed groups: {processed_groups}, "
            f"duplicate users removed: {deleted_users}, social links moved: {moved_social}"
        )

        if not apply_changes:
            self.stdout.write(
                self.style.WARNING(
                    "No database changes were made. Re-run with --apply after reviewing dry-run output."
                )
            )

    def _duplicate_emails(self):
        grouped = (
            User.objects.exclude(email__isnull=True)
            .exclude(email="")
            .annotate(email_norm=Lower("email"))
            .values("email_norm")
            .annotate(total=Count("id"))
            .filter(total__gt=1)
            .order_by("email_norm")
        )
        return [row["email_norm"] for row in grouped]

    def _choose_primary_user(self, users):
        # Prefer the oldest non-social account so legacy logins remain the primary identity.
        for user in users:
            has_google_social = UserSocialAuth.objects.filter(user=user, provider="google-oauth2").exists()
            if not has_google_social:
                return user
        return users[0]

    def _merge_one_duplicate(self, primary_user, duplicate_user):
        with transaction.atomic():
            self._merge_user_fields(primary_user, duplicate_user)
            moved_social = self._move_social_auth_records(primary_user, duplicate_user)
            self._merge_profile_data(primary_user, duplicate_user)
            self._reassign_related_records(primary_user, duplicate_user)
            duplicate_user.delete()
        return moved_social

    def _merge_user_fields(self, primary_user, duplicate_user):
        updated_fields = []

        if not primary_user.first_name and duplicate_user.first_name:
            primary_user.first_name = duplicate_user.first_name
            updated_fields.append("first_name")

        if not primary_user.last_name and duplicate_user.last_name:
            primary_user.last_name = duplicate_user.last_name
            updated_fields.append("last_name")

        if not primary_user.phone and duplicate_user.phone:
            primary_user.phone = duplicate_user.phone
            updated_fields.append("phone")

        if duplicate_user.is_verified and not primary_user.is_verified:
            primary_user.is_verified = True
            updated_fields.append("is_verified")

        if updated_fields:
            primary_user.save(update_fields=updated_fields)

    def _move_social_auth_records(self, primary_user, duplicate_user):
        moved = 0
        for social in UserSocialAuth.objects.filter(user=duplicate_user):
            exists = UserSocialAuth.objects.filter(
                user=primary_user,
                provider=social.provider,
                uid=social.uid,
            ).exists()
            if exists:
                social.delete()
            else:
                social.user = primary_user
                social.save(update_fields=["user"])
                moved += 1
        return moved

    def _merge_profile_data(self, primary_user, duplicate_user):
        self._merge_traveler_profile(primary_user, duplicate_user)
        self._merge_vendor_profile(primary_user, duplicate_user)
        self._merge_admin_profile(primary_user, duplicate_user)

    def _merge_traveler_profile(self, primary_user, duplicate_user):
        primary = TravelerProfile.objects.filter(user=primary_user).first()
        duplicate = TravelerProfile.objects.filter(user=duplicate_user).first()
        if duplicate is None:
            return

        if primary is None:
            duplicate.user = primary_user
            duplicate.save(update_fields=["user"])
            return

        changed = []
        merge_fields = ["date_of_birth", "gender", "nationality", "bio", "avatar"]
        for field_name in merge_fields:
            primary_value = getattr(primary, field_name)
            duplicate_value = getattr(duplicate, field_name)
            if (primary_value in (None, "")) and duplicate_value not in (None, ""):
                setattr(primary, field_name, duplicate_value)
                changed.append(field_name)

        if changed:
            primary.save(update_fields=changed)

        duplicate.delete()

    def _merge_vendor_profile(self, primary_user, duplicate_user):
        primary = VendorProfile.objects.filter(user=primary_user).first()
        duplicate = VendorProfile.objects.filter(user=duplicate_user).first()
        if duplicate is None:
            return

        if primary is None:
            duplicate.user = primary_user
            duplicate.save(update_fields=["user"])
            return

        changed = []
        merge_fields = [
            "business_name",
            "owner_name",
            "tagline",
            "website",
            "license_number",
            "business_address",
            "description",
            "bank_name",
            "account_number",
            "routing_number",
            "paypal_email",
            "logo",
            "cover_image",
            "business_license",
            "document",
        ]

        for field_name in merge_fields:
            primary_value = getattr(primary, field_name)
            duplicate_value = getattr(duplicate, field_name)
            if (primary_value in (None, "")) and duplicate_value not in (None, ""):
                setattr(primary, field_name, duplicate_value)
                changed.append(field_name)

        if duplicate.is_approved and not primary.is_approved:
            primary.is_approved = True
            changed.append("is_approved")

        if duplicate.is_verified and not primary.is_verified:
            primary.is_verified = True
            changed.append("is_verified")

        if changed:
            primary.save(update_fields=list(dict.fromkeys(changed)))

        duplicate.delete()

    def _merge_admin_profile(self, primary_user, duplicate_user):
        primary = AdminProfile.objects.filter(user=primary_user).first()
        duplicate = AdminProfile.objects.filter(user=duplicate_user).first()
        if duplicate is None:
            return

        if primary is None:
            duplicate.user = primary_user
            duplicate.save(update_fields=["user"])
            return

        changed = []
        if not primary.bio and duplicate.bio:
            primary.bio = duplicate.bio
            changed.append("bio")

        if not primary.avatar and duplicate.avatar:
            primary.avatar = duplicate.avatar
            changed.append("avatar")

        if changed:
            primary.save(update_fields=changed)

        duplicate.delete()

    def _reassign_related_records(self, primary_user, duplicate_user):
        handled_models = {
            TravelerProfile,
            VendorProfile,
            AdminProfile,
            UserSocialAuth,
        }

        for model in apps.get_models():
            if model in handled_models or model is User:
                continue

            for field in model._meta.get_fields():
                if not getattr(field, "concrete", False):
                    continue
                if not getattr(field, "is_relation", False):
                    continue
                if getattr(field, "auto_created", False):
                    continue
                if field.related_model is not User:
                    continue

                field_name = field.name

                if field.one_to_one:
                    duplicate_record = model.objects.filter(**{field_name: duplicate_user}).first()
                    if duplicate_record is None:
                        continue

                    primary_exists = model.objects.filter(**{field_name: primary_user}).exists()
                    if primary_exists:
                        duplicate_record.delete()
                    else:
                        setattr(duplicate_record, field_name, primary_user)
                        duplicate_record.save(update_fields=[field_name])
                else:
                    model.objects.filter(**{field_name: duplicate_user}).update(**{field_name: primary_user})
