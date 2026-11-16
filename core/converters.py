import uuid
from django.urls.converters import UUIDConverter


class InventoryUUIDConverter(UUIDConverter):
    """Accept SQL Server's upper/lower GUIDs and always reverse canonical URLs."""
    regex = UUIDConverter.regex.replace('a-f', 'a-fA-F')

    def to_url(self, value):
        return str(uuid.UUID(str(value)))
