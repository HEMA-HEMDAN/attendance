from django import forms
from apps.groups.models import Group
from .models import Schedule


from django.utils.html import format_html
from django.utils.safestring import mark_safe

class GroupSelectWidget(forms.Select):
    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex=subindex, attrs=attrs)
        val = getattr(value, 'value', value)
        if val:
            try:
                grp = Group.objects.only('id', 'course_offering_id').get(pk=val)
                option['attrs']['data-course-offering'] = grp.course_offering_id
            except (Group.DoesNotExist, ValueError, TypeError):
                pass
        return option

    def render(self, name, value, attrs=None, renderer=None):
        html = super().render(name, value, attrs=attrs, renderer=renderer)
        script = """
        <script>
        (function() {
            if (window._group_filter_script_loaded) return;
            window._group_filter_script_loaded = true;

            function getJQuery() {
                if (window.django && window.django.jQuery) return window.django.jQuery;
                if (window.jQuery) return window.jQuery;
                return null;
            }

            function filterGroupByDataAttr(groupSelect, offeringId, targetVal) {
                if (!groupSelect) return false;
                var options = groupSelect.options;
                if (!options) return false;

                if (!offeringId) {
                    groupSelect.disabled = true;
                    groupSelect.innerHTML = '<option value="">Select a course offering first...</option>';
                    return false;
                }

                var matchingCount = 0;
                var hasMatch = false;

                for (var i = 0; i < options.length; i++) {
                    var opt = options[i];
                    if (!opt.value) continue;
                    var attrOffering = opt.getAttribute('data-course-offering');
                    if (!attrOffering || String(attrOffering) === String(offeringId)) {
                        matchingCount++;
                        opt.hidden = false;
                        opt.disabled = false;
                        if (targetVal && String(opt.value) === String(targetVal)) {
                            hasMatch = true;
                        }
                    } else {
                        opt.hidden = true;
                        opt.disabled = true;
                    }
                }

                if (matchingCount > 0) {
                    groupSelect.disabled = false;
                    if (!hasMatch && targetVal) {
                        groupSelect.value = '';
                    }
                    return true;
                }
                return false;
            }

            function loadGroupsForOffering(groupSelect, offeringId, targetVal) {
                if (!groupSelect) return;

                if (!offeringId) {
                    groupSelect.disabled = true;
                    groupSelect.innerHTML = '<option value="">Select a course offering first...</option>';
                    return;
                }

                var hasLocalMatches = filterGroupByDataAttr(groupSelect, offeringId, targetVal);

                var url = '/admin/groups-by-offering/?offering_id=' + encodeURIComponent(offeringId);
                fetch(url)
                    .then(function(res) {
                        if (!res.ok) throw new Error('HTTP ' + res.status);
                        return res.json();
                    })
                    .then(function(data) {
                        var groups = (data && data.groups) ? data.groups : [];
                        if (groups.length === 0 && hasLocalMatches) {
                            return;
                        }

                        groupSelect.innerHTML = '<option value="">---------</option>';
                        var hasMatch = false;

                        groups.forEach(function(g) {
                            var opt = document.createElement('option');
                            opt.value = g.id;
                            opt.textContent = g.name;
                            opt.setAttribute('data-course-offering', offeringId);
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
                        console.warn('AJAX group fetch warning:', err);
                        if (hasLocalMatches) {
                            groupSelect.disabled = false;
                        }
                    });
            }

            function setupRow(container) {
                var courseSelect = container.querySelector('select[name$="course_offering"]');
                var groupSelect = container.querySelector('select[name$="group"]');

                if (!courseSelect || !groupSelect) return;

                var initialGroupVal = groupSelect.value;
                loadGroupsForOffering(groupSelect, courseSelect.value, initialGroupVal);
            }

            function init() {
                var $ = getJQuery();

                document.querySelectorAll('tr.form-row, div.inline-related, fieldset.module, form, .form-row').forEach(setupRow);

                if ($) {
                    $(document).on('change select2:select select2:clear', 'select[name$="course_offering"]', function() {
                        var $courseSelect = $(this);
                        var offeringId = $courseSelect.val();
                        var $container = $courseSelect.closest('tr.form-row, div.inline-related, fieldset.module, form, .form-row');
                        var $groupSelect = $container.find('select[name$="group"]');

                        if ($groupSelect.length) {
                            loadGroupsForOffering($groupSelect[0], offeringId, null);
                        }
                    });

                    $(document).on('formset:added', function(event, $row) {
                        if ($row && $row.length) {
                            setupRow($row[0]);
                        }
                    });
                }

                document.addEventListener('change', function(e) {
                    if (e.target && e.target.name && e.target.name.endsWith('course_offering')) {
                        var courseSelect = e.target;
                        var container = courseSelect.closest('tr.form-row, div.inline-related, fieldset.module, form, .form-row');
                        if (container) {
                            var groupSelect = container.querySelector('select[name$="group"]');
                            if (groupSelect) {
                                loadGroupsForOffering(groupSelect, courseSelect.value, null);
                            }
                        }
                    }
                });

                document.addEventListener('formset:added', function(event) {
                    setupRow(event.target);
                });
            }

            if (document.readyState === 'loading') {
                document.addEventListener('DOMContentLoaded', init);
            } else {
                init();
            }
        })();
        </script>
        """
        return format_html('{}{}', mark_safe(html), mark_safe(script))


class ScheduleAdminForm(forms.ModelForm):
    class Meta:
        model = Schedule
        fields = '__all__'
        widgets = {
            'group': GroupSelectWidget(),
        }

    def clean(self):
        cleaned_data = super().clean()
        course_offering = cleaned_data.get('course_offering')
        group = cleaned_data.get('group')

        if group and course_offering:
            if group.course_offering_id != course_offering.id:
                self.add_error('group', f"Group '{group.name}' does not belong to course offering '{course_offering}'.")
        return cleaned_data
