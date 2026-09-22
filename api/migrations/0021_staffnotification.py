from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('api', '0020_membership_program_latest')]
    operations = [
        migrations.CreateModel(
            name='StaffNotification',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('event_key', models.CharField(max_length=160)),
                ('channel', models.CharField(max_length=20, choices=[('line', 'LINE'), ('wechat', 'WeChat')])),
                ('event_type', models.CharField(max_length=40)),
                ('payload', models.JSONField(default=dict)),
                ('status', models.CharField(max_length=32, default='awaiting_configuration')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={'constraints': [models.UniqueConstraint(fields=('event_key', 'channel'), name='unique_staff_notification_event')]},
        ),
    ]
