"""ML classifier (PRD §C3.2): as labelled blocks accumulate, train a model to
predict the activity from event metadata, reducing reliance on the AI pass.

Trains a TF-IDF + LogisticRegression pipeline on classified_blocks, using the
consultant_override where present (the human-corrected truth) else the engine
classification. Saved with joblib. Pure-Python deps (scikit-learn, joblib).
"""
import os
from db.models import ClassifiedBlock, ActivityEvent, Participant, ActivityCatalog

MODEL_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "model.joblib")


def _training_rows(session, study_id=None):
    q = (session.query(ClassifiedBlock, ActivityEvent)
         .join(ActivityEvent,
               (ActivityEvent.participant_id == ClassifiedBlock.participant_id) &
               (ActivityEvent.start_ts == ClassifiedBlock.start_ts)))
    if study_id:
        q = q.join(Participant, ClassifiedBlock.participant_id == Participant.id) \
             .filter(Participant.study_id == study_id)
    X, y = [], []
    for blk, ev in q.all():
        label = blk.consultant_override or blk.activity_id
        if not label:
            continue
        X.append(f"{ev.app_name} {ev.window_title_hash} {ev.category}")
        y.append(label)
    return X, y


def train(session, study_id=None):
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    import joblib

    X, y = _training_rows(session, study_id)
    if len(set(y)) < 2:
        return {"trained": False, "reason": "need >=2 activity classes with data"}
    pipe = Pipeline([
        ("tfidf", TfidfVectorizer(lowercase=True, ngram_range=(1, 2))),
        ("clf", LogisticRegression(max_iter=1000)),
    ])
    pipe.fit(X, y)
    joblib.dump(pipe, MODEL_PATH)
    acc = pipe.score(X, y)
    return {"trained": True, "samples": len(y), "classes": len(set(y)),
            "train_accuracy": round(acc, 3), "model_path": MODEL_PATH}


def predict(text: str):
    import joblib
    if not os.path.exists(MODEL_PATH):
        return None
    pipe = joblib.load(MODEL_PATH)
    activity_id = pipe.predict([text])[0]
    conf = float(max(pipe.predict_proba([text])[0]))
    return activity_id, conf
