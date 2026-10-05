from django import forms
from apps.groups.models import Group
from .models import Schedule


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
