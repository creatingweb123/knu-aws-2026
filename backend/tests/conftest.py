from hypothesis import settings

# 첫 실행의 import·정규식 컴파일 시간 때문에 deadline 초과가 불규칙하게 난다. 시간 제한은 두지 않는다.
settings.register_profile("default", deadline=None)
settings.load_profile("default")
