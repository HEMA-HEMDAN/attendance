document.addEventListener('DOMContentLoaded', function() {
    function filterGroupOptions(container) {
        var courseSelect = container.querySelector('select[name$="-course_offering"]');
        var groupSelect = container.querySelector('select[name$="-group"]');

        if (!courseSelect || !groupSelect) return;

        function updateGroups() {
            var selectedOfferingId = courseSelect.value;
            var currentGroupVal = groupSelect.value;
            var hasMatchingGroup = false;

            Array.from(groupSelect.options).forEach(function(opt) {
                if (!opt.value) {
                    opt.hidden = false;
                    opt.disabled = false;
                    return;
                }
                var offeringId = opt.getAttribute('data-course-offering');
                if (!selectedOfferingId || offeringId === selectedOfferingId) {
                    opt.hidden = false;
                    opt.disabled = false;
                    if (opt.value === currentGroupVal) {
                        hasMatchingGroup = true;
                    }
                } else {
                    opt.hidden = true;
                    opt.disabled = true;
                }
            });

            if (!hasMatchingGroup && currentGroupVal) {
                groupSelect.value = "";
            }
        }

        courseSelect.addEventListener('change', updateGroups);
        updateGroups();
    }

    // Filter all existing schedule rows on page load
    document.querySelectorAll('tr.form-row, div.inline-related, fieldset.module').forEach(filterGroupOptions);

    // Filter newly added inline formset rows
    document.addEventListener('formset:added', function(event) {
        filterGroupOptions(event.target);
    });
});
