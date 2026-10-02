from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('courses', '0002_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='schedule',
            name='room_label',
            field=models.CharField(blank=True, max_length=255),
        ),
    ]