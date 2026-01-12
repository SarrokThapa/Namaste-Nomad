function togglePassword(inputId) {
    const input = document.getElementById(inputId);
    const type = input.type === 'password' ? 'text' : 'password';
    input.type = type;
}

// File Upload Handler
document.addEventListener('DOMContentLoaded', function() {
    const fileUpload = document.getElementById('fileUpload');
    const fileInput = document.getElementById('fileInput');
    const fileName = document.getElementById('fileName');

    if (fileUpload && fileInput) {
        // Click to upload
        fileUpload.addEventListener('click', function() {
            fileInput.click();
        });

        // File selection
        fileInput.addEventListener('change', function() {
            if (this.files && this.files[0]) {
                const file = this.files[0];
                const fileSize = (file.size / 1024 / 1024).toFixed(2);
                
                if (fileSize > 10) {
                    alert('File size must be less than 10MB');
                    this.value = '';
                    return;
                }
                
                fileName.textContent = `Selected: ${file.name} (${fileSize} MB)`;
            }
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
                fileInput.files = e.dataTransfer.files;
                const file = e.dataTransfer.files[0];
                const fileSize = (file.size / 1024 / 1024).toFixed(2);
                
                if (fileSize > 10) {
                    alert('File size must be less than 10MB');
                    fileInput.value = '';
                    return;
                }
                
                fileName.textContent = `Selected: ${file.name} (${fileSize} MB)`;
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