import json

from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required

from rest_framework import status
from rest_framework.response import Response
from rest_framework.decorators import api_view

from .serializer import (UserSerializer, RepoSerializer)


@api_view(['GET'])
@login_required
def user(request, format=None):
    username = request.user.get_username()
    user = User.objects.get(username=username)

    serializer = UserSerializer(user, many=False)
    return Response(serializer.data)


@api_view(['GET'])
@login_required
def user_repos(request, format=None):
    username = request.user.get_username()
    repo_base = username

    serializer = RepoSerializer(username=username, repo_base=repo_base)
    return Response(serializer.user_owned_repos)


@api_view(['GET'])
@login_required
def user_accessible_repos(request, format=None):
    username = request.user.get_username()
    repo_base = username
    serializer = RepoSerializer(username=username, repo_base=repo_base)

    return Response(serializer.user_accessible_repos())


@api_view(['GET', 'POST'])
@login_required
def collaborator_repos(request, repo_base, format=None):
    username = request.user.get_username()
    serializer = RepoSerializer(username=username, repo_base=repo_base)

    if request.method == 'GET':
        if username == repo_base:
            return Response(serializer.user_owned_repos())
        else:
            return Response(serializer.specific_collab_repos(repo_base))

    if request.method == 'POST':
        body = json.loads(request.body)
        repo_name = body['repo']
        success = serializer.create_repo(repo_name)
        if success:
            return Response(
                serializer.user_accessible_repos(),
                status=status.HTTP_201_CREATED)
        else:
            return Response(
                serializer.user_accessible_repos(),
                status=status.HTTP_400_BAD_REQUEST)
