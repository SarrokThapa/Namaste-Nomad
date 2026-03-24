function togglePassword(inputId, toggleButton) {
    const input = document.getElementById(inputId);
    if (!input) {
        return;
    }
    const isHidden = input.type === 'password';
    input.type = isHidden ? 'text' : 'password';
    if (toggleButton) {
        toggleButton.setAttribute('aria-pressed', isHidden ? 'true' : 'false');
        toggleButton.setAttribute('aria-label', isHidden ? 'Hide password' : 'Show password');
    }
}

// File Upload Handler
document.addEventListener('DOMContentLoaded', function() {
    const fileUpload = document.getElementById('fileUpload');
    const fileInput = document.getElementById('fileInput');
    const fileName = document.getElementById('fileName');
    const allowedExtensions = new Set(['pdf', 'jpg', 'jpeg', 'png']);

    const validateSelectedFile = (inputEl) => {
        if (!inputEl || !inputEl.files || !inputEl.files[0]) {
            return true;
        }

        const file = inputEl.files[0];
        const fileSizeMb = file.size / 1024 / 1024;
        const ext = (file.name.split('.').pop() || '').toLowerCase();

        if (!allowedExtensions.has(ext)) {
            alert('Please upload PDF, JPG, JPEG, or PNG file only.');
            inputEl.value = '';
            if (fileName) {
                fileName.textContent = '';
            }
            return false;
        }

        if (fileSizeMb > 10) {
            alert('File size must be less than 10MB.');
            inputEl.value = '';
            if (fileName) {
                fileName.textContent = '';
            }
            return false;
        }

        if (fileName) {
            fileName.textContent = `Selected: ${file.name} (${fileSizeMb.toFixed(2)} MB)`;
        }
        return true;
    };

    if (fileUpload && fileInput) {
        // File selection
        fileInput.addEventListener('change', function() {
            fileInput.setCustomValidity('');
            validateSelectedFile(this);
        });

        // Drag and drop
        fileUpload.addEventListener('dragover', function(e) {
            e.preventDefault();
            this.style.borderColor = '#3b82f6';
            this.style.background = '#f9fafb';
        });

        fileUpload.addEventListener('dragleave', function() {
            this.style.borderColor = '#d1d5db';
            this.style.background = 'white';
        });

        fileUpload.addEventListener('drop', function(e) {
            e.preventDefault();
            this.style.borderColor = '#d1d5db';
            this.style.background = 'white';
            
            if (e.dataTransfer.files.length) {
                try {
                    const dt = new DataTransfer();
                    dt.items.add(e.dataTransfer.files[0]);
                    fileInput.files = dt.files;
                } catch (_err) {
                    alert('Drag and drop is not supported in this browser. Please click to attach file.');
                    return;
                }
                validateSelectedFile(fileInput);
            }
        });
    }

    // OTP Input Auto-format
    const otpInput = document.getElementById('otpInput');
    if (otpInput) {
        otpInput.addEventListener('input', function(e) {
            // Only allow numbers
            this.value = this.value.replace(/[^0-9]/g, '');
        });

        otpInput.addEventListener('paste', function(e) {
            e.preventDefault();
            const pastedData = e.clipboardData.getData('text');
            const numbers = pastedData.replace(/[^0-9]/g, '').slice(0, 6);
            this.value = numbers;
        });
    }

    // Form validation
    const forms = document.querySelectorAll('form');
    forms.forEach(form => {
        form.addEventListener('submit', function(e) {
            const password = this.querySelector('input[name="password"]');
            const confirmPassword = this.querySelector('input[name="confirm_password"]');
            const hasVendorFileInput = fileInput && this.contains(fileInput);
            
            if (password && confirmPassword) {
                if (password.value !== confirmPassword.value) {
                    e.preventDefault();
                    alert('Passwords do not match!');
                    return false;
                }
                
                if (password.value.length < 6) {
                    e.preventDefault();
                    alert('Password must be at least 6 characters long!');
                    return false;
                }
            }

            if (hasVendorFileInput) {
                if (!fileInput.files || !fileInput.files.length) {
                    e.preventDefault();
                    fileInput.setCustomValidity('Please attach a verification document before registering.');
                    fileInput.reportValidity();
                    alert('Please attach a verification document before registering.');
                    return false;
                }
                fileInput.setCustomValidity('');
                if (!validateSelectedFile(fileInput)) {
                    e.preventDefault();
                    return false;
                }
            }
        });
    });

    // Auto-dismiss alerts after 5 seconds
    const alerts = document.querySelectorAll('.alert');
    alerts.forEach(alert => {
        setTimeout(() => {
            alert.style.transition = 'opacity 0.5s';
            alert.style.opacity = '0';
            setTimeout(() => alert.remove(), 500);
        }, 5000);
    });
});

/* ============================= */
/* Landing Page Styles */
/* ============================= */
