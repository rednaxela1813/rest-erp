from rest_framework import serializers
from .models import Organization, OrgNote, OrganizationMember




class OrganizationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organization
        fields = ("public_id", "name", "legal_form", "registration_number", "vat_number", "country")
        read_only_fields = ("public_id",)

class OrgNoteSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrgNote
        fields = ("public_id", "title")
        read_only_fields = ("public_id",)
        

class OrgMemberUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrganizationMember
        fields = ["role"]     



class OrgMemberListSerializer(serializers.ModelSerializer):
    # Чтобы тест проходил в обоих вариантах:
    # - item["email"]
    # - или item["user"]["email"]
    #
    # Мы дадим "email" верхним уровнем (самый удобный для фронта).
    email = serializers.EmailField(source="user.email", read_only=True)

    class Meta:
        model = OrganizationMember
        fields = ["id", "email", "role", "created_at"]
        read_only_fields = fields


class OrgMemberCreateSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(write_only=True)
    
    class Meta:
        model = OrganizationMember
        fields = ["email", "role"]
        extra_kwargs = {
            'role': {'required': True}
        }
    
    def create(self, validated_data):
        from django.contrib.auth import get_user_model
        
        email = validated_data.pop('email')
        User = get_user_model()
        
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            raise serializers.ValidationError({"email": "User with this email does not exist."})
        
        # Проверяем, что пользователь еще не является участником этой организации
        if OrganizationMember.objects.filter(org=validated_data['org'], user=user).exists():
            raise serializers.ValidationError({"email": "User is already a member of this organization."})
        
        return OrganizationMember.objects.create(user=user, **validated_data)
    
    def to_representation(self, instance):
        # Возвращаем представление с помощью OrgMemberListSerializer
        return OrgMemberListSerializer(instance).data