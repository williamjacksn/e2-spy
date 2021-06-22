document.getElementById('select-department').addEventListener('change', function (ev) {
    const selected_option = this.options[this.selectedIndex];
    const url_params = new URLSearchParams(window.location.search);
    url_params.set('department', selected_option.value);
    window.location.search = url_params;
});
