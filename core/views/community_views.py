"""Community feed and interactions.

Owns the public community feed, the per-user community dashboard, and
all post/comment/like/tag mutations. Each entry point first checks the
admin "enable_community" site setting via ``_ensure_community_enabled``.
"""

# NOTE: file > 300 lines — split deferred. Posts, comments, likes and
# tag-vendor mutations all share the `from ..utils.helpers import (...)`
# bundle and the same community-enabled gate; splitting would force the
# same hub bundle into multiple sibling files.

import mimetypes

from ..utils.helpers import (
    Comment,
    CommentForm,
    Max,
    Notification,
    Post,
    PostEditForm,
    PostForm,
    PostMedia,
    _community_posts,
    _get_or_create_traveler_profile,
    add_points,
    create_notification,
    get_object_or_404,
    get_user_model,
    login_required,
    messages,
    notify_admins,
    redirect,
    render,
    reverse,
    sync_badges_for_user,
    transaction,
)
from ..services.site_settings import get_site_settings


def _ensure_community_enabled(request):
    """Return a redirect response if community is admin-disabled, else None."""
    if get_site_settings().enable_community:
        return None
    messages.error(request, 'Community is currently disabled by admin.')
    return redirect('home')


def community_feed(request):
    """Public community feed page (read-only for anonymous, post-actions for logged in)."""
    disabled_response = _ensure_community_enabled(request)
    if disabled_response:
        return disabled_response

    posts = _community_posts(viewer=request.user)
    vendors = get_user_model().objects.filter(user_type='vendor').select_related('vendor_profile').order_by('username')

    return render(request, 'core/community_feed.html', {
        'posts': posts,
        'is_dashboard': False,
        'force_show_post_form': False,
        'vendors': vendors,
    })


@login_required(login_url='traveler_login')
def community_dashboard(request):
    """Logged-in user's community dashboard with their own posts visible first."""
    disabled_response = _ensure_community_enabled(request)
    if disabled_response:
        return disabled_response

    if getattr(request.user, 'user_type', '') != 'traveler':
        messages.error(request, 'Traveler access only.')
        return redirect('home')

    traveler_profile = _get_or_create_traveler_profile(request.user)
    posts = _community_posts(viewer=request.user)
    vendors = get_user_model().objects.filter(user_type='vendor').select_related('vendor_profile').order_by('username')

    return render(request, 'core/community_dashboard.html', {
        'posts': posts,
        'is_dashboard': True,
        'force_show_post_form': True,
        'traveler_profile': traveler_profile,
        'active_page': 'community',
        'vendors': vendors,
    })


@login_required(login_url='account_login_choice')
def community_post_create(request):
    """Create a new community post (with media + tagged vendors); awards points for travelers."""
    disabled_response = _ensure_community_enabled(request)
    if disabled_response:
        return disabled_response

    next_url = request.POST.get('next') or reverse('community_feed')
    if request.method != 'POST':
        return redirect(next_url)

    form = PostForm(request.POST, request.FILES)
    if form.is_valid():
        post = form.save(commit=False)
        post.user = request.user
        post.save()
        if getattr(request.user, 'user_type', '') == 'traveler':
            add_points(request.user, 'post', 10)
            sync_badges_for_user(request.user)
        media_files = form.cleaned_data.get('media_files', [])
        for index, media_file in enumerate(media_files, start=1):
            content_type = (getattr(media_file, 'content_type', '') or '').lower()
            if not content_type:
                guessed_type, _ = mimetypes.guess_type(getattr(media_file, 'name', ''))
                content_type = (guessed_type or '').lower()
            media_type = (
                PostMedia.MEDIA_VIDEO
                if content_type.startswith('video/')
                else PostMedia.MEDIA_IMAGE
            )
            PostMedia.objects.create(
                post=post,
                media_file=media_file,
                media_type=media_type,
                order=index,
            )

        tag_ids = []
        for raw_id in request.POST.getlist('tagged_vendors'):
            try:
                tag_ids.append(int(raw_id))
            except (TypeError, ValueError):
                continue
        if tag_ids:
            vendors = get_user_model().objects.filter(user_type='vendor', id__in=tag_ids)
            post.tagged_vendors.set(vendors)
            for vendor in vendors:
                if vendor.id != request.user.id:
                    create_notification(
                        vendor,
                        f'You were tagged in a community post by {post.user.get_full_name() or post.user.username}.',
                        Notification.TYPE_COMMUNITY_POST,
                        related_object_id=post.id,
                    )
        else:
            post.tagged_vendors.clear()

        notify_admins(
            f'New community post created by {post.user.get_full_name() or post.user.username}.',
            Notification.TYPE_COMMUNITY_POST,
            related_object_id=post.id,
        )
        messages.success(request, 'Post shared successfully.')
    else:
        error_messages = []
        error_messages.extend([str(error) for error in form.non_field_errors()])
        for field, field_errors in form.errors.items():
            if field == '__all__':
                continue
            for error in field_errors:
                error_messages.append(f'{field}: {error}')

        if error_messages:
            messages.error(request, ' '.join(error_messages))
        else:
            messages.error(request, 'Please upload at least one photo or video and add a caption.')

    return redirect(next_url)


@login_required(login_url='account_login_choice')
def community_post_edit(request, post_id):
    """Edit an existing community post owned by the current user (caption, media, tags)."""
    disabled_response = _ensure_community_enabled(request)
    if disabled_response:
        return disabled_response

    post = get_object_or_404(
        Post.objects.select_related('user').prefetch_related('media', 'tagged_vendors'),
        id=post_id,
        user=request.user,
    )
    next_url = request.POST.get('next') or request.GET.get('next') or reverse('community_feed')
    vendors = get_user_model().objects.filter(user_type='vendor').select_related('vendor_profile').order_by('username')

    if request.method == 'POST':
        form = PostEditForm(request.POST, request.FILES, instance=post)
        if form.is_valid():
            media_files = request.FILES.getlist('media_files')
            remove_ids = []
            for raw_id in request.POST.getlist('remove_media'):
                try:
                    remove_ids.append(int(raw_id))
                except (TypeError, ValueError):
                    continue
            remove_legacy = request.POST.get('remove_legacy') == '1'

            existing_media_ids = set(post.media.values_list('id', flat=True))
            remove_ids = [media_id for media_id in remove_ids if media_id in existing_media_ids]
            remaining = len(existing_media_ids) - len(remove_ids)
            if post.image and not remove_legacy:
                remaining += 1
            remaining += len(media_files)

            if remaining < 1:
                form.add_error(None, 'Please keep at least one photo or video.')
            else:
                with transaction.atomic():
                    post.caption = form.cleaned_data['caption']
                    post.save(update_fields=['caption'])

                    if remove_ids:
                        PostMedia.objects.filter(post=post, id__in=remove_ids).delete()

                    if remove_legacy and post.image:
                        post.image.delete(save=False)
                        post.image = None
                        post.save(update_fields=['image'])

                    if media_files:
                        max_order = post.media.aggregate(max_order=Max('order'))['max_order'] or 0
                        for offset, media_file in enumerate(media_files, start=1):
                            content_type = (getattr(media_file, 'content_type', '') or '').lower()
                            media_type = (
                                PostMedia.MEDIA_VIDEO
                                if content_type.startswith('video/')
                                else PostMedia.MEDIA_IMAGE
                            )
                            PostMedia.objects.create(
                                post=post,
                                media_file=media_file,
                                media_type=media_type,
                                order=max_order + offset,
                            )

                    tag_ids = []
                    for raw_id in request.POST.getlist('tagged_vendors'):
                        try:
                            tag_ids.append(int(raw_id))
                        except (TypeError, ValueError):
                            continue
                    if tag_ids:
                        tagged = get_user_model().objects.filter(user_type='vendor', id__in=tag_ids)
                        post.tagged_vendors.set(tagged)
                    else:
                        post.tagged_vendors.clear()

                messages.success(request, 'Post updated successfully.')
                return redirect(next_url)
        messages.error(request, 'Please correct the errors below.')
    else:
        form = PostEditForm(instance=post)

    existing_media = list(post.media.all())
    legacy_media = post.image

    return render(request, 'core/community_post_edit.html', {
        'post': post,
        'form': form,
        'vendors': vendors,
        'existing_media': existing_media,
        'legacy_media': legacy_media,
        'next_url': next_url,
        'selected_vendor_ids': {vendor.id for vendor in post.tagged_vendors.all()},
    })


@login_required(login_url='account_login_choice')
def community_post_delete(request, post_id):
    """Delete a community post owned by the current user."""
    disabled_response = _ensure_community_enabled(request)
    if disabled_response:
        return disabled_response

    if request.method != 'POST':
        return redirect('community_feed')
    post = get_object_or_404(Post, id=post_id, user=request.user)
    next_url = request.POST.get('next') or reverse('community_feed')
    post.delete()
    messages.success(request, 'Post deleted.')
    return redirect(next_url)


@login_required(login_url='account_login_choice')
def community_post_tag_vendor(request, post_id):
    """Redirect to the post-edit page anchored on the tag-vendors section."""
    disabled_response = _ensure_community_enabled(request)
    if disabled_response:
        return disabled_response

    post = get_object_or_404(Post, id=post_id, user=request.user)
    next_url = request.GET.get('next') or reverse('community_feed')
    edit_url = reverse('community_post_edit', kwargs={'post_id': post.id})
    return redirect(f'{edit_url}?next={next_url}#tag-vendors')


@login_required(login_url='account_login_choice')
def community_comment_create(request, post_id):
    """Add a comment (or single-level reply by the original poster) to a community post."""
    disabled_response = _ensure_community_enabled(request)
    if disabled_response:
        return disabled_response

    next_url = request.POST.get('next') or f"{reverse('community_feed')}#post-{post_id}"
    if request.method != 'POST':
        return redirect(next_url)

    post = get_object_or_404(Post, id=post_id)
    form = CommentForm(request.POST)
    if form.is_valid():
        comment = form.save(commit=False)
        comment.post = post
        comment.user = request.user
        parent_id = request.POST.get('parent_id')
        if parent_id:
            parent_comment = get_object_or_404(Comment, id=parent_id, post=post)
            if parent_comment.parent_id:
                messages.error(request, 'Replies can only be added to top-level comments.')
                return redirect(next_url)
            if request.user.id != post.user_id:
                messages.error(request, 'Only the original poster can reply to comments.')
                return redirect(next_url)
            comment.parent = parent_comment
        comment.save()
        if post.user_id != request.user.id:
            create_notification(
                post.user,
                f'{request.user.get_full_name() or request.user.username} commented on your post.',
                Notification.TYPE_COMMENT,
                related_object_id=post.id,
            )
        if comment.parent_id and comment.parent.user_id != request.user.id:
            create_notification(
                comment.parent.user,
                f'{request.user.get_full_name() or request.user.username} replied to your comment.',
                Notification.TYPE_COMMENT,
                related_object_id=post.id,
            )
        messages.success(request, 'Comment added.')
    else:
        messages.error(request, 'Please write a comment before submitting.')

    return redirect(next_url)


@login_required(login_url='account_login_choice')
def community_post_like_toggle(request, post_id):
    """Toggle the current user's like on a post; awards points to traveler authors."""
    disabled_response = _ensure_community_enabled(request)
    if disabled_response:
        return disabled_response

    next_url = request.POST.get('next') or f"{reverse('community_feed')}#post-{post_id}"
    if request.method != 'POST':
        return redirect(next_url)

    post = get_object_or_404(Post, id=post_id)
    if post.likes.filter(id=request.user.id).exists():
        post.likes.remove(request.user)
    else:
        post.likes.add(request.user)
        if post.user_id != request.user.id:
            if getattr(post.user, 'user_type', '') == 'traveler':
                add_points(post.user, 'like_received', 2)
                sync_badges_for_user(post.user)
            create_notification(
                post.user,
                f'{request.user.get_full_name() or request.user.username} liked your community post.',
                Notification.TYPE_LIKE,
                related_object_id=post.id,
            )

    return redirect(next_url)
