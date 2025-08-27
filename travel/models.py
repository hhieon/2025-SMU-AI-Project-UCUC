# travel/models.py
from django.db import models

class Diary(models.Model):
    session_key = models.CharField(max_length=40, null=True, blank=True, db_index=True)
    title = models.CharField(max_length=200)
    content = models.TextField()
    mood_emoji = models.CharField(max_length=10, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    llm_provider = models.CharField(max_length=50, choices=[
        ("openai", "OpenAI"),
        ("gemini", "Gemini"),
    ], default="openai")
    llm_model = models.CharField(max_length=100, default="gpt-4o-mini")  # 세부 모델

    def __str__(self):
        return self.title
