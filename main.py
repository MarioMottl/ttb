from twitchio.ext import commands
import os
from typing import Dict, Optional, List
import yaml
import re
import unicodedata
import time


class TextCleaner:
    @staticmethod
    def clean_text(text: str) -> str:
        """Clean text by removing special characters and normalizing"""
        text = text.lower()
        text = unicodedata.normalize("NFKD", text)
        text = text.encode("ASCII", "ignore").decode("ASCII")
        text = re.sub(r"(.)\1+", r"\1", text)
        text = re.sub(r"[,\.\'\"~\-_\?\!\*]", "", text)
        text = " ".join(text.split())
        return text


class SpamDetector:
    def __init__(self, spam_patterns: List[str], min_similarity: float = 0.7):
        self.spam_patterns = [pattern.lower() for pattern in spam_patterns]
        self.min_similarity = min_similarity
        self.cleaner = TextCleaner()

    def is_spam(self, message: str) -> bool:
        cleaned_msg = self.cleaner.clean_text(message)
        return any(pattern in cleaned_msg for pattern in self.spam_patterns)


class WordMonitorBot(commands.Bot):
    def __init__(
        self,
        token: str,
        prefix: str,
        initial_channels: list[str],
        word_responses: Dict[str, str],
        spam_patterns: List[str],
        response_delay: float = 3.0,
        config_path: str = "config.yml",
    ):
        self._channels = initial_channels
        super().__init__(token=token, prefix=prefix, initial_channels=initial_channels)
        self.word_responses = word_responses
        self.spam_detector = SpamDetector(spam_patterns)
        self.response_delay = response_delay
        self.last_response_time = 0
        self.config_path = config_path

    def save_config(self):
        """Save current configuration to file"""
        config = {
            "channels": self._channels,
            "word_responses": self.word_responses,
            "spam_patterns": self.spam_detector.spam_patterns,
            "response_delay": self.response_delay,
        }
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                yaml.dump(config, f, default_flow_style=False)
            return True
        except Exception as e:
            print(f"Failed to save config: {e}")
            return False

    async def event_ready(self):
        """Called once when the bot goes online."""
        print(f"Bot is ready! Username: {self.nick}")
        print(f"Monitoring channels: {', '.join(self._channels)}")
        print(f"Monitoring for words: {', '.join(self.word_responses.keys())}")
        print(
            f"Monitoring for spam patterns: {', '.join(self.spam_detector.spam_patterns)}"
        )
        print(f"Response delay set to {self.response_delay} seconds")

    @commands.command(name="addresponse")
    async def add_response(self, ctx: commands.Context, trigger: str, *, response: str):
        """Add or update a word response. Usage: !addresponse trigger response text"""
        if not (
            ctx.author.is_mod or ctx.author.name.lower() == ctx.channel.name.lower()
        ):
            return

        self.word_responses[trigger.lower()] = response
        if self.save_config():
            await ctx.send(f"Added response for '{trigger}'")
        else:
            await ctx.send("Failed to save configuration")

    @commands.command(name="delresponse")
    async def delete_response(self, ctx: commands.Context, trigger: str):
        """Delete a word response. Usage: !delresponse trigger"""
        if not (
            ctx.author.is_mod or ctx.author.name.lower() == ctx.channel.name.lower()
        ):
            return

        if trigger.lower() in self.word_responses:
            del self.word_responses[trigger.lower()]
            if self.save_config():
                await ctx.send(f"Deleted response for '{trigger}'")
            else:
                await ctx.send("Failed to save configuration")
        else:
            await ctx.send(f"No response found for '{trigger}'")

    @commands.command(name="responses")
    async def list_responses(self, ctx: commands.Context):
        """List all word responses. Usage: !responses"""
        if not (
            ctx.author.is_mod or ctx.author.name.lower() == ctx.channel.name.lower()
        ):
            return

        if not self.word_responses:
            await ctx.send("No responses configured")
            return

        response_list = ", ".join(
            f"{trigger}: {response}"
            for trigger, response in self.word_responses.items()
        )
        await ctx.send(f"Current responses: {response_list}")

    @commands.command(name="addspam")
    async def add_spam_pattern(self, ctx: commands.Context, pattern: str):
        """Add a spam pattern. Usage: !addspam pattern"""
        if not (
            ctx.author.is_mod or ctx.author.name.lower() == ctx.channel.name.lower()
        ):
            return

        self.spam_detector.spam_patterns.append(pattern.lower())
        if self.save_config():
            await ctx.send(f"Added spam pattern '{pattern}'")
        else:
            await ctx.send("Failed to save configuration")

    @commands.command(name="delspam")
    async def delete_spam_pattern(self, ctx: commands.Context, pattern: str):
        """Delete a spam pattern. Usage: !delspam pattern"""
        if not (
            ctx.author.is_mod or ctx.author.name.lower() == ctx.channel.name.lower()
        ):
            return

        pattern = pattern.lower()
        if pattern in self.spam_detector.spam_patterns:
            self.spam_detector.spam_patterns.remove(pattern)
            if self.save_config():
                await ctx.send(f"Deleted spam pattern '{pattern}'")
            else:
                await ctx.send("Failed to save configuration")
        else:
            await ctx.send(f"Spam pattern '{pattern}' not found")

    @commands.command(name="spampatterns")
    async def list_spam_patterns(self, ctx: commands.Context):
        """List all spam patterns. Usage: !spampatterns"""
        if not (
            ctx.author.is_mod or ctx.author.name.lower() == ctx.channel.name.lower()
        ):
            return

        patterns = ", ".join(self.spam_detector.spam_patterns)
        await ctx.send(f"Current spam patterns: {patterns}")

    async def event_message(self, message):
        """Called every time a message is sent in chat."""
        if message.echo:
            return

        if message.content.startswith("!"):
            await self.handle_commands(message)
            return

        if self.spam_detector.is_spam(message.content):
            is_mod = message.author.is_mod
            is_broadcaster = message.author.name.lower() == message.channel.name.lower()

            if not (is_mod or is_broadcaster):
                try:
                    await message.channel.send(f"/timeout {message.author.name} 3")
                    await message.delete()
                    print(f"Timeout user {message.author.name} for spam")
                    return
                except Exception as e:
                    print(f"Failed to timeout user: {e}")
                    return
            else:
                print(f"Skipping timeout for privileged user {message.author.name}")
                return

        current_time = time.time()
        if current_time - self.last_response_time < self.response_delay:
            return

        cleaned_content = TextCleaner.clean_text(message.content)
        words_in_message = cleaned_content.split()

        for trigger_word, response in self.word_responses.items():
            cleaned_trigger = TextCleaner.clean_text(trigger_word)
            if cleaned_trigger in words_in_message:
                await message.channel.send(response)
                self.last_response_time = current_time
                return


def load_config(config_path: str = "config.yml") -> Optional[dict]:
    try:
        print(f"Loading config from: {os.path.abspath(config_path)}")
        with open(config_path, "r", encoding="utf-8") as file:
            config = yaml.safe_load(file)

            if "channels" not in config:
                print("Warning: No channels specified in config")
                return None

            config.setdefault("word_responses", {})
            config.setdefault(
                "spam_patterns",
                [
                    "casino",
                ],
            )
            config.setdefault("response_delay", 1.0)

            return config
    except Exception as e:
        print(f"Error loading config: {e}")
        return None


def main():
    config = load_config()
    if not config:
        print("Failed to load configuration. Exiting.")
        return

    token = "TWITCH_OAUTH_TOKEN"

    bot = WordMonitorBot(
        token=token,
        prefix="!",
        initial_channels=config["channels"],
        word_responses=config["word_responses"],
        spam_patterns=config["spam_patterns"],
        response_delay=config.get("response_delay", 1.0),
        config_path="config.yml",
    )
    bot.run()


if __name__ == "__main__":
    main()
