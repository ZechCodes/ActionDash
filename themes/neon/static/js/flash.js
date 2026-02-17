// Flash message dismissal
document.querySelectorAll('.sk-flash-dismiss').forEach(btn => {
    btn.addEventListener('click', () => {
        btn.closest('.sk-flash').remove();
    });
});
// Auto-dismiss success messages after 5 seconds
document.querySelectorAll('.sk-flash-success[data-dismissible]').forEach(flash => {
    setTimeout(() => {
        flash.style.opacity = '0';
        setTimeout(() => flash.remove(), 300);
    }, 5000);
});
