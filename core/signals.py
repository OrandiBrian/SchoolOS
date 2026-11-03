from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import School, SchoolAdmissionCounter


@receiver(post_save, sender=School)
def create_admission_counter(sender, instance, created, **kwargs):
    if created:
        SchoolAdmissionCounter.objects.get_or_create(school=instance)
