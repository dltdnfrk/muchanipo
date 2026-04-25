# Korea Persona Seeds

이 디렉토리는 한국 지역/직업 기반 council persona seed 원천 데이터를 두기 위한 자리입니다.
실제 Nemotron-Personas-Korea 데이터 파일은 저장소에 포함하지 않습니다. 사용자가 라이선스와
용량을 확인한 뒤 별도로 다운로드해서 배치해야 합니다.

## Source

- Dataset: Nemotron-Personas-Korea
- URL: https://huggingface.co/datasets/nvidia/Nemotron-Personas-Korea
- License: CC BY 4.0
- Notes: 약 1M records, KOSIS grounded 한국 synthetic persona 데이터셋

KorNAT 같은 한국어 alignment dataset은 평가/정렬 참고 자료로 함께 검토할 수 있지만, 이
seed 디렉토리의 1차 원천은 Nemotron-Personas-Korea입니다.

## Expected Files

`src/council/persona_sampler.py`는 기본적으로 parquet 원천을 가정하지만 stdlib만 사용하기
위해 JSON, JSONL, CSV export도 읽을 수 있습니다. parquet 파일만 있는 경우에는 사용자가
별도 변환 도구로 export한 뒤 sampler에 넘기는 방식을 권장합니다.

예시:

```text
vault/personas/seeds/korea/nemotron_personas_korea.jsonl
vault/personas/seeds/korea/nemotron_personas_korea.csv
```
