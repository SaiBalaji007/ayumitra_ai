from django.db import transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import MedicalDocument


@receiver(post_delete, sender=MedicalDocument)
def delete_file_with_document(sender, instance, **kwargs):
    """
    Remove the stored file when its database row is deleted, including cascades such as account
    deletion. Runs after commit so a rolled-back delete never loses the file.
    """
    if not instance.file:
        return
    storage, name = instance.file.storage, instance.file.name
    transaction.on_commit(lambda: storage.delete(name))
