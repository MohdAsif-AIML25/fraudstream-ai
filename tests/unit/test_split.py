"""The split must be chronological, complete and non-overlapping."""

import pandas as pd 
import pytest 

from app.models.split import chronological_split 

@pytest.fixture
def frame() -> pd.DataFrame:
    times=pd.date_range("2026-09-01",periods=100,freq="h",tz="UTC")
    return pd.DataFrame({"event_time":times, "is_fraud":[0]*100})

def test_no_rows_lost_or_duplicates(frame):
    train,val,test=chronological_split(frame)
    assert len(train)+len(val)+len(test)==len(frame)
    assert set(train.index).isdisjoint(val.index) and set(val.index).isdisjoint(test.index)

def test_every_split_is_strictly_later_than_the_previous(frame):
    train,val,test=chronological_split(frame)
    assert train["event_time"].max() < val["event_time"].min()
    assert val["event_time"].max() <test["event_time"].min()

def test_same_timestamp_never_crosses_a_boundary():
    times = pd.to_datetime(["2026-09-01"] * 50 + ["2026-09-02"] * 50, utc=True)
    train, val, test = chronological_split(pd.DataFrame({"event_time": times}))
    for part in (train, val, test):
        if len(part):
            boundary_day = part["event_time"].iloc[0]
            # all rows of a timestamp live in exactly one split
            assert sum((p["event_time"] == boundary_day).any() for p in (train, val, test)) == 1


def test_invalid_fractions_are_rejected(frame):
    with pytest.raises(ValueError):
        chronological_split(frame, train_frac=0.9, val_frac=0.2)

