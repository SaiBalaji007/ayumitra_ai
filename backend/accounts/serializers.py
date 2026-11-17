from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

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
        extra_kwargs = {
            # Our validate_email gives one clear, case-insensitive duplicate message, so drop the
            # model's default UniqueValidator ("user with this email already exists.").
            "email": {"validators": []},
            "first_name": {"required": True, "allow_blank": False},
            "last_name": {"required": False},
        }

    def validate_email(self, value):
        value = User.objects.normalize_email(value).lower()
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("An account with this email already exists.")
        return value

    def validate(self, attrs):
        # Run Django's password validators against the would-be user (similarity, length, common)
        # and report failures on the password field, where the form shows them.
        candidate = User(email=attrs["email"], first_name=attrs.get("first_name", ""), last_name=attrs.get("last_name", ""))
        try:
            validate_password(attrs["password"], candidate)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"password": list(exc.messages)}) from exc
        return attrs

    def create(self, validated_data):
        # `username` is required by AbstractUser; mirror the email so it stays unique.
        try:
            with transaction.atomic():
                return User.objects.create_user(username=validated_data["email"], **validated_data)
        except IntegrityError as exc:  # two simultaneous sign-ups with the same email
            raise serializers.ValidationError({"email": ["An account with this email already exists."]}) from exc


class EmailTokenObtainPairSerializer(TokenObtainPairSerializer):
    """Login with the email in any letter case. Accounts are stored lowercased at registration."""

    def validate(self, attrs):
        attrs[self.username_field] = User.objects.normalize_email(attrs.get(self.username_field, "")).strip().lower()
        return super().validate(attrs)


class UserUpdateSerializer(serializers.ModelSerializer):
    """Name changes only. Email is the login identity and is not editable here."""

    class Meta:
        model = User
        fields = ["id", "email", "first_name", "last_name"]
        read_only_fields = ["id", "email"]


class PasswordChangeSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True, trim_whitespace=False)
    new_password = serializers.CharField(write_only=True, trim_whitespace=False)

    def validate_current_password(self, value):
        if not self.context["request"].user.check_password(value):
            raise serializers.ValidationError("Current password is incorrect.")
        return value

    def validate(self, attrs):
        user = self.context["request"].user
        try:
            validate_password(attrs["new_password"], user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"new_password": list(exc.messages)}) from exc
        if attrs["new_password"] == attrs["current_password"]:
            raise serializers.ValidationError({"new_password": ["The new password must differ from the current one."]})
        return attrs


class AccountDeleteSerializer(serializers.Serializer):
    password = serializers.CharField(write_only=True, trim_whitespace=False)

    def validate_password(self, value):
        if not self.context["request"].user.check_password(value):
            raise serializers.ValidationError("Password is incorrect.")
        return value
