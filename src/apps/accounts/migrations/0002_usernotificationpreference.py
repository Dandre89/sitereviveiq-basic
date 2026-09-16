import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='UserNotificationPreference',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('notify_critical_findings', models.BooleanField(default=True)),
                ('notify_score_drops', models.BooleanField(default=True)),
                ('notify_scan_completed', models.BooleanField(default=True)),
                ('notify_new_opportunities', models.BooleanField(default=True)),
                ('notify_returning_issues', models.BooleanField(default=True)),
                ('notify_credits_exhausted', models.BooleanField(default=True)),
                ('notify_proposal_response', models.BooleanField(default=True)),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='notification_preference', to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]
