from django.shortcuts import get_object_or_404
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema
from rest_framework import filters, generics, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.api import AdminOnly, ordered_pagination
from fitness import services
from fitness.models import Article, SavedArticle
from fitness.serializers import (
    AnthropometryInputSerializer,
    AnthropometryLogSerializer,
    ArticleInputSerializer,
    ArticleSerializer,
    FitnessProfileSerializer,
    SaveArticleOutputSerializer,
    SavedArticleSerializer,
)


class UserProfileView(generics.GenericAPIView):
    """Retrieve or update the user's fitness profile and targets. Staff can manage any member's targets."""

    permission_classes = [IsAuthenticated]
    serializer_class = FitnessProfileSerializer

    def _target_user(self, request):
        if request.user.role == "admin":
            uid = request.query_params.get("user_id") or request.data.get("user_id")
            if uid:
                from accounts.models import User

                return get_object_or_404(User, pk=uid)
        return request.user

    @extend_schema(responses=FitnessProfileSerializer)
    def get(self, request):
        target = self._target_user(request)
        profile = services.get_profile(target)
        return Response(FitnessProfileSerializer(profile).data)

    @extend_schema(request=FitnessProfileSerializer, responses=FitnessProfileSerializer)
    def patch(self, request):
        target = self._target_user(request)
        serializer = FitnessProfileSerializer(
            services.get_profile(target), data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        updated = services.update_profile(target, serializer.validated_data)
        return Response(FitnessProfileSerializer(updated).data)

    @extend_schema(request=FitnessProfileSerializer, responses=FitnessProfileSerializer)
    def put(self, request):
        return self.patch(request)


class AnthropometryView(generics.ListCreateAPIView):
    """List historical anthropometry records or log a new weigh-in/body check."""

    permission_classes = [IsAuthenticated]
    pagination_class = ordered_pagination("-logged_at", "-created_at", "-id")
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_serializer_class(self):
        if self.request.method == "POST":
            return AnthropometryInputSerializer
        return AnthropometryLogSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return services.AnthropometryLog.objects.none()
        return services.list_anthropometry(self.request.user)

    @extend_schema(responses=AnthropometryLogSerializer(many=True))
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    @extend_schema(
        request=AnthropometryInputSerializer, responses={201: AnthropometryLogSerializer}
    )
    def post(self, request, *args, **kwargs):
        serializer = AnthropometryInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        photo_file = request.FILES.get("check_in_photo")
        log = services.log_anthropometry(
            request.user, serializer.validated_data, photo_file=photo_file
        )
        return Response(
            AnthropometryLogSerializer(log, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )


class ArticleViewSet(viewsets.ModelViewSet):
    """Fitness knowledge hub & educational article feed. Staff can publish & manage articles; members can read & save."""

    queryset = Article.objects.all()
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["category", "is_pinned"]
    search_fields = ["title", "excerpt", "source", "tags"]
    ordering_fields = ["created_at", "reading_time_minutes", "title", "is_pinned"]
    ordering = ["-is_pinned", "-created_at"]

    def get_permissions(self):
        if self.action in ["create", "update", "partial_update", "destroy"]:
            return [AdminOnly()]
        return [IsAuthenticated()]

    def get_serializer_class(self):
        if self.action in ["create", "update", "partial_update"]:
            return ArticleInputSerializer
        return ArticleSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        saved_only = self.request.query_params.get("saved_only")
        if saved_only in ["true", "1", True]:
            user = self.request.user
            if user.is_authenticated:
                saved_ids = SavedArticle.objects.filter(user=user).values_list("article_id", flat=True)
                qs = qs.filter(pk__in=saved_ids)
            else:
                qs = qs.none()
        return qs

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(
            ArticleSerializer(serializer.instance, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
            headers=headers,
        )

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(
            ArticleSerializer(serializer.instance, context={"request": request}).data,
            status=status.HTTP_200_OK,
        )

    @extend_schema(request=None, responses={200: SaveArticleOutputSerializer})
    @action(detail=True, methods=["post"], url_path="save")
    def save_article(self, request, pk=None):
        article = self.get_object()
        SavedArticle.objects.get_or_create(user=request.user, article=article)
        return Response(
            {"is_saved": True, "article_id": article.id, "message": "Article saved to reading list."},
            status=status.HTTP_200_OK,
        )

    @extend_schema(request=None, responses={200: SaveArticleOutputSerializer})
    @action(detail=True, methods=["post"], url_path="unsave")
    def unsave_article(self, request, pk=None):
        article = self.get_object()
        SavedArticle.objects.filter(user=request.user, article=article).delete()
        return Response(
            {"is_saved": False, "article_id": article.id, "message": "Article removed from saved."},
            status=status.HTTP_200_OK,
        )

    @extend_schema(responses={200: SavedArticleSerializer(many=True)})
    @action(detail=False, methods=["get"], url_path="saved")
    def saved(self, request):
        saved_items = (
            SavedArticle.objects.filter(user=request.user).select_related("article").order_by("-saved_at")
        )
        page = self.paginate_queryset(saved_items)
        if page is not None:
            serializer = SavedArticleSerializer(page, many=True, context={"request": request})
            return self.get_paginated_response(serializer.data)
        serializer = SavedArticleSerializer(saved_items, many=True, context={"request": request})
        return Response(serializer.data)

