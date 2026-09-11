import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('workspaces', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='Subscription',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('stripe_customer_id', models.CharField(blank=True, max_length=255)),
                ('stripe_subscription_id', models.CharField(blank=True, max_length=255)),
                ('stripe_price_id', models.CharField(blank=True, max_length=255)),
                ('status', models.CharField(choices=[
                    ('incomplete', 'Incomplete — not yet linked to Stripe'),
                    ('incomplete_expired', 'Incomplete (expired)'),
                    ('trialing', 'Trialing'),
                    ('active', 'Active'),
                    ('past_due', 'Past due'),
                    ('canceled', 'Canceled'),
                    ('unpaid', 'Unpaid'),
                    ('paused', 'Paused'),
                ], default='incomplete', max_length=25)),
                ('current_period_end', models.DateTimeField(blank=True, null=True)),
                ('cancel_at_period_end', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('workspace', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='subscription',
                    to='workspaces.workspace',
                )),
            ],
        ),
        migrations.AddIndex(
            model_name='subscription',
            index=models.Index(fields=['stripe_customer_id'], name='billing_sub_stripe__cust_idx'),
        ),
        migrations.AddIndex(
            model_name='subscription',
            index=models.Index(fields=['stripe_subscription_id'], name='billing_sub_stripe__subs_idx'),
        ),
    ]
