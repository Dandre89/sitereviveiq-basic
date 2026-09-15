from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0002_subscription_intended_interval'),
    ]

    operations = [
        migrations.AddField(
            model_name='subscription',
            name='migrated_to_pro_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='subscription',
            name='migrated_to_pro_workspace_id',
            field=models.UUIDField(blank=True, null=True),
        ),
    ]
