"""Local webcam hand-gesture recognition using MediaPipe Hands when available."""
from __future__ import annotations

def _gesture(lm):
    pts=[(p.x,p.y) for p in lm]
    def above(i,j): return pts[i][1] < pts[j][1]-0.04
    fingers=[above(8,6),above(12,10),above(16,14),above(20,18)]
    thumb=pts[4][0] > pts[3][0]+0.04 or pts[4][0] < pts[3][0]-0.04
    total=sum(fingers)+int(thumb)
    if total>=4: return "open palm"
    if total==0: return "fist"
    if fingers[0] and fingers[1] and not fingers[2] and not fingers[3]: return "peace"
    if fingers[0] and total<=2: return "pointing"
    if total==1 and thumb: return "thumb gesture"
    return "unknown"

def _handler(parameters, player=None, **_):
    try:
        import cv2, mediapipe as mp
    except Exception as exc:
        return f"Gesture recognition dependencies are unavailable: {exc}"
    seconds=max(.5,min(5,float(parameters.get("seconds",2) or 2)))
    cap=cv2.VideoCapture(0)
    if not cap.isOpened(): return "Camera could not be opened for gesture detection."
    hands=mp.solutions.hands.Hands(static_image_mode=False,max_num_hands=1,min_detection_confidence=.55,min_tracking_confidence=.55)
    seen=[]
    import time
    end=time.time()+seconds
    try:
        while time.time()<end:
            ok,frame=cap.read()
            if not ok: continue
            rgb=cv2.cvtColor(frame,cv2.COLOR_BGR2RGB)
            res=hands.process(rgb)
            if res.multi_hand_landmarks: seen.append(_gesture(res.multi_hand_landmarks[0].landmark))
    finally:
        hands.close(); cap.release()
    if not seen: return "No hand gesture detected."
    from collections import Counter
    return "Detected gesture: " + Counter(seen).most_common(1)[0][0]

TOOL={"name":"gesture_control","description":"Use the webcam to locally recognize common hand gestures such as open palm, fist, peace, and pointing.","parameters":{"type":"OBJECT","properties":{"seconds":{"type":"NUMBER","description":"Recognition window in seconds, 0.5 to 5"}},"required":[]},"handler":_handler}
