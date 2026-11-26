# sam build가 AiCardFunction에만 쓴다(Metadata.BuildMethod: makefile, design §17.1, BE-Q80).
# 다른 함수는 CodeUri src/ + requirements.txt 기본 빌더라 이 파일은 산출물에 복사만 되고 실행되지 않는다.
# 공통 코드는 저장소에 하나만 두고 빌드 때 산출물로 모은다. AI 의존성은 해시 고정 잠금 파일로만 설치한다.
build-AiCardFunction:
	cp -r common domain handlers agent prompts "$(ARTIFACTS_DIR)/"
	python -m pip install --no-cache-dir --only-binary=:all: --no-deps --require-hashes -r ai-requirements.lock -t "$(ARTIFACTS_DIR)"
	find "$(ARTIFACTS_DIR)" -name "__pycache__" -prune -exec rm -rf {} +
