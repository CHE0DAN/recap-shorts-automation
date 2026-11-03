"""질문 문장 모음. 평가 스크립트와 실제 코드가 같은 질문을 쓰도록 한곳에 둔다(키 'prefix.변형')."""
from __future__ import annotations

from . import client as c

VARIANTS = ["A", "B"]

# ---- 3.2 장면 적합도
MATCH_STATE = "A short vertical video in Korean narration; each sentence of the narration is shown over pictures."


def match_q(variant: str, sentence: str) -> dict:
    if variant == "A":
        return c.yes_no(f"Is this picture a good one to show on screen while the narrator says: '{sentence}'?")
    return c.yes_no(f"Does this picture illustrate or directly relate to what this sentence says: '{sentence}'?")


# ---- 3.3 그림 검사
INSPECT_KEYS = ["face", "personal_text", "text_or_logo", "real_person_like"]
INSPECT = {
    "face": {"A": "Is a person's face clearly visible in this picture?",
             "B": "Can you see a real human face in this picture that someone could recognize?"},
    "personal_text": {"A": "Does the picture show a username, nickname, account ID or phone number?",
                      "B": "Is any readable account name, handle or personal identifier visible in the picture?"},
    "text_or_logo": {"A": "Does the picture contain readable text, letters or a logo?",
                     "B": "Is there writing, a caption or a brand logo visible anywhere in the picture?"},
    "real_person_like": {"A": "Does this picture look like a photo or realistic depiction of a real, recognizable person?",
                         "B": "Is a real person (not a drawing or a fictional character) shown with a realistic face?"},
}
INSPECT_STATE = "A picture to be used in a video."


def inspect_q(key: str, variant: str) -> dict:
    return c.yes_no(INSPECT[key][variant])


# ---- 3.1 주제 분류
CATEGORIES = {
    "politics": "politics, politicians, government, elections",
    "crime": "a crime, accident, incident or lawsuit",
    "sexual": "sexual or sexually suggestive content",
    "entertainment": "celebrities, entertainment, K-pop, TV",
    "sports": "sports, baseball, games, athletes",
    "life_economy": "everyday life, jobs, money, economy, military service, consumer topics",
    "other": "anything else",
}
RISK_KEYS = ["person_attack", "sexual", "unverified_claim"]
RISKS = {
    "person_attack": {"A": "Is the main point of this post to attack, insult or mock a specific named person?",
                      "B": "Does this post mainly consist of criticism, ridicule or hatred aimed at a particular individual?"},
    "sexual": {"A": "Does this post sexually objectify someone or contain sexual or lewd content?",
               "B": "Is this post sexually suggestive, lewd or about someone's body in a sexual way?"},
    "unverified_claim": {"A": "Does this post spread an unverified rumor or accusation about a real person or group?",
                         "B": "Is this post based on a suspicion or allegation that has not been confirmed?"},
}
INTEREST = {
    "A": "How interesting would this post be to a general audience that does not follow baseball?",
    "B": "Would an ordinary person who is not a baseball fan find this post interesting and want to watch a short video about it?",
}
INTEREST_LEVELS = ["not at all", "slightly", "somewhat", "quite", "very"]
CATEGORY_Q = {
    "A": "What is the main subject of this community post?",
    "B": "Which field does this community post belong to?",
}
TRIAGE_STATE = "A post from a Korean online community gallery (translate mentally from Korean). "


def category_q(variant: str) -> dict:
    return c.choice(CATEGORY_Q[variant], CATEGORIES)


def risk_q(key: str, variant: str) -> dict:
    return c.yes_no(RISKS[key][variant])


def interest_q(variant: str) -> dict:
    return c.score(INTEREST[variant], INTEREST_LEVELS)


# ---- 3.4 영상 점검 (영상 점검 질문 + 자막 잘림)
def watch_questions(topic: bool) -> dict:
    q = {
        "opens_finished": c.yes_no("Does the video open on a strong, clear first scene related to its topic?"),
        "face": c.yes_no("Is a person's face clearly visible in the video?"),
        "music": c.yes_no("Is background music audible in the video - a song, instruments or a melody?"),
        "narration": c.yes_no("Is a person's narration voice audible in the video?"),
        "caption_cut": c.yes_no("Is any caption or text cut off at the edge of the frame so that it cannot be read in full?"),
    }
    if topic:
        q["topic_match"] = c.yes_no("Does the video's content match the topic named in the state?",
                                    yes="The video is about that topic.", no="The video is about something else.")
    return q


# ---- 3.5 목소리
def voice_q(variant: str, sentence: str) -> dict:
    if variant == "A":
        return c.yes_no(f"Does this sound clearly say the Korean sentence: '{sentence}'?")
    return c.yes_no(f"Is the spoken sentence in this audio the same as: '{sentence}'?")
VOICE_STATE = "A short audio clip of a Korean narrator."
