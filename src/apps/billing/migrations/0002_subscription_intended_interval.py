from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='subscription',
            name='intended_interval',
            field=models.CharField(blank=True, choices=[('monthly', 'Monthly'), ('annual', 'Annual')], max_length=10),
        ),
    ]
