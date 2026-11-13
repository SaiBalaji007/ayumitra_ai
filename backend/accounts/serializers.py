from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "email", "first_name", "last_name"]
        read_only_fields = fields


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, trim_whitespace=False)

    class Meta:
        model = User
        fields = ["id", "email", "password", "first_name", "last_name"]
        extra_kwargs = {"first_name": {"required": True}, "last_name": {"required": False}}

    def validate_email(self, value):
        value = User.objects.normalize_email(value).lower()
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("An account with this email already exists.")
        return value

    def validate(self, attrs):
        # Run Django's password validators against the would-be user (similarity, length, common).
        validate_password(attrs["password"], User(email=attrs["email"], first_name=attrs.get("first_name", "")))
        return attrs

    def create(self, validated_data):
        # `username` is required by AbstractUser; mirror the email so it stays unique.
        return User.objects.create_user(username=validated_data["email"], **validated_data)
