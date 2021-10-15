document.getElementById('modal-job-notes').addEventListener('show.bs.modal', (ev) => {
    const source = ev.relatedTarget;
    document.querySelector('#job-number').textContent = source.dataset.jobNumber;
    document.querySelector('input[name="job_number"]').value = source.dataset.jobNumber;
    document.querySelector('input[name="next_view"]').value = source.dataset.nextView;
    document.querySelector('textarea[name="notes"]').value = source.dataset.notes;
});
