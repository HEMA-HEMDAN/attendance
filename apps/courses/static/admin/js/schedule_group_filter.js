(function() {
    function initGroupFiltering() {
        var $ = (window.django && window.django.jQuery) ? window.django.jQuery : (window.jQuery || null);

        function setupRow(container) {
            var courseSelect = container.querySelector('select[name$="course_offering"]');
            var groupSelect = container.querySelector('select[name$="group"]');

            if (!courseSelect || !groupSelect) return;

            // Prevent duplicate initialization on same row
            if (groupSelect.dataset.filterInitialized === 'true') return;
            groupSelect.dataset.filterInitialized = 'true';

            var initialGroupVal = groupSelect.value;

            function loadGroupsForOffering(offeringId, targetVal) {
                if (!offeringId) {
                    groupSelect.disabled = true;
                    groupSelect.innerHTML = '<option value="">Select a course offering first...</option>';
                    return;
                }

                groupSelect.disabled = true;
                groupSelect.innerHTML = '<option value="">Loading groups...</option>';

                fetch('/admin/groups-by-offering/?offering_id=' + encodeURIComponent(offeringId))
                    .then(function(res) {
                        if (!res.ok) throw new Error('HTTP ' + res.status);
                        return res.json();
                    })
                    .then(function(data) {
                        groupSelect.innerHTML = '<option value="">---------</option>';
                        var groups = (data && data.groups) ? data.groups : [];
                        var hasMatch = false;

                        groups.forEach(function(g) {
                            var opt = document.createElement('option');
                            opt.value = g.id;
                            opt.textContent = g.name;
                            if (targetVal && String(g.id) === String(targetVal)) {
                                opt.selected = true;
                                hasMatch = true;
                            }
                            groupSelect.appendChild(opt);
                        });

                        groupSelect.disabled = false;
                        if (!hasMatch && targetVal) {
                            groupSelect.value = '';
                        }
                    })
                    .catch(function(err) {
                        console.error('Failed to load groups for course offering:', err);
                        groupSelect.innerHTML = '<option value="">Error loading groups</option>';
                        groupSelect.disabled = true;
                    });
            }

            // Initial load
            if (courseSelect.value) {
                loadGroupsForOffering(courseSelect.value, initialGroupVal);
            } else {
                groupSelect.disabled = true;
                groupSelect.innerHTML = '<option value="">Select a course offering first...</option>';
            }

            // Trigger fetch when course offering changes
            function onChange() {
                var selectedOfferingId = courseSelect.value;
                loadGroupsForOffering(selectedOfferingId, null);
            }

            courseSelect.addEventListener('change', onChange);
            if ($) {
                $(courseSelect).on('change select2:select select2:clear', onChange);
            }
        }

        function filterAll() {
            document.querySelectorAll('tr.form-row, div.inline-related, fieldset.module, form').forEach(setupRow);
        }

        filterAll();

        // Support dynamically added inline rows
        document.addEventListener('formset:added', function(event) {
            setupRow(event.target);
        });

        if ($) {
            $(document).on('formset:added', function(event, $row) {
                if ($row && $row.length) {
                    setupRow($row[0]);
                }
            });
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initGroupFiltering);
    } else {
        initGroupFiltering();
    }
})();
