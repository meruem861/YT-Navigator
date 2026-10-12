"""Chat history model."""

from django.db import models


class ChatHistoryMessage(models.Model):
    """A message of a user's conversation with the channel assistant.

    Attributes:
        user: Owner of the conversation.
        role: "human" or "ai".
        content: The user's text, or the assistant's answer as JSON ({"placeholder": markdown, "videos": [...]}).
        created_at: When the message was sent.
    """

    user = models.ForeignKey("User", on_delete=models.CASCADE, related_name="chat_messages")
    role = models.CharField(max_length=10, choices=[("human", "Human"), ("ai", "AI")])
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        """Meta class for the chat history model."""

        ordering = ["created_at", "id"]
