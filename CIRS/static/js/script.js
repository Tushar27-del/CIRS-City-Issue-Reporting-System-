// Show admin department only if role = admin
document.addEventListener('DOMContentLoaded', () => {
    const roleSelect = document.getElementById('role_select');
    const adminContainer = document.getElementById('admin_department_container');

    roleSelect.addEventListener('change', () => {
        if (roleSelect.value === 'admin') {
            adminContainer.style.display = 'block';
        } else {
            adminContainer.style.display = 'none';
        }
    });
});
