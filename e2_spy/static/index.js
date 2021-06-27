function build_spinner() {
    const div = document.createElement('div');
    div.classList.add('spinner-border', 'spinner-border-sm');
    return div;
}

document.querySelectorAll('a.slow').forEach((el) => {
    el.addEventListener('click', (ev) => {
        const space = document.createTextNode(' ');
        ev.target.appendChild(space);
        ev.target.appendChild(build_spinner());
    });
});
