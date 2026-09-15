import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0003_subscription_migrated_to_pro'),
        ('workspaces', '0001_initial'),
        ('scans', '0002_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='CreditBalance',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('balance', models.IntegerField(default=0)),
                ('cycle_allotment', models.PositiveIntegerField(default=0)),
                ('cycle_resets_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('workspace', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='credit_balance',
                    to='workspaces.workspace',
                )),
            ],
        ),
        migrations.CreateModel(
            name='CreditTransaction',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('delta', models.IntegerField()),
                ('reason', models.CharField(choices=[
                    ('cycle_grant', 'Monthly grant'),
                    ('scan_spend', 'Scan'),
                    ('scan_refund', 'Scan refund'),
                    ('topup_purchase', 'Credit top-up purchase'),
                    ('manual_adjustment', 'Manual adjustment'),
                ], max_length=20)),
                ('stripe_payment_intent_id', models.CharField(blank=True, max_length=255)),
                ('balance_after', models.IntegerField()),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('workspace', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='credit_transactions',
                    to='workspaces.workspace',
                )),
                ('scan', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='credit_transactions',
                    to='scans.scan',
                )),
                ('created_by', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='+',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='credittransaction',
            index=models.Index(fields=['workspace', '-created_at'], name='billing_credittx_ws_created_idx'),
        ),
    ]
