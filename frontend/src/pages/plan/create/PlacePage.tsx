import { useState } from 'react';
import { Navigate, useLocation, useNavigate, useSearchParams } from 'react-router-dom';

import type { PlaceInput } from '../../../api/types';
import { PageTitle } from '../../../components/PageTitle';
import { PrimaryButton } from '../../../components/PrimaryButton';
import { TextArea } from '../../../components/TextArea';
import { TextField } from '../../../components/TextField';
import { emptyPlace, usePlanDraft } from '../../../state/planDraft';
import { LIMITS, validatePlace } from '../../../utils/validation';
import type { FieldErrors } from '../../../utils/validation';
import { clearPlaceFlags, withoutFlag } from './cardForm';
import styles from './Create.module.css';

const FORM_PATH = '/plans/new/form';

/** `?index=n`이 유효하면 n, 없으면 null(추가), 잘못되면 undefined */
function parseIndex(raw: string | null, count: number): number | null | undefined {
  if (raw === null) return null;
  if (!/^\d+$/.test(raw)) return undefined;
  const n = Number(raw);
  return n < count ? n : undefined;
}

/**
 * 3-3. 장소 추가(FE-CRT-07). `?index=n`이면 그 장소를 고친다(FE-Q20).
 * 저장하면 폼으로 돌아간다. 폼에서 들어왔으면 뒤로 가서 기록이 쌓이지 않게 한다.
 */
export function PlacePage() {
  const navigate = useNavigate();
  const location = useLocation();
  const [params] = useSearchParams();
  const { draft, update } = usePlanDraft();
  const places = draft?.form.places ?? [];
  const index = parseIndex(params.get('index'), places.length);
  const [place, setPlace] = useState<PlaceInput>(() =>
    typeof index === 'number' ? { ...places[index] } : emptyPlace(),
  );
  const [errors, setErrors] = useState<FieldErrors>({});

  if (!draft || !draft.story.trim()) return <Navigate to="/plans/new" replace />;
  if (index === undefined || (index === null && places.length >= LIMITS.maxPlaces)) {
    return <Navigate to={FORM_PATH} replace />;
  }

  const setField = (key: keyof PlaceInput, value: string) => {
    setPlace((p) => ({ ...p, [key]: value }));
    if (errors[key]) setErrors((prev) => Object.fromEntries(Object.entries(prev).filter(([p]) => p !== key)));
  };

  const onSave = () => {
    const errs = validatePlace(place);
    if (Object.keys(errs).length > 0) {
      setErrors(errs);
      return;
    }
    const saved = {
      name: place.name.trim(),
      activity: place.activity.trim(),
      whyChosen: place.whyChosen.trim(),
    };
    update((d) => {
      const next = [...d.form.places];
      if (index === null) next.push(saved);
      else next[index] = saved;
      // 고친 장소의 AI 안내는 지운다(FE-Q25). 추가는 'places'(장소 없음) 안내를 지운다
      const flags = index === null ? withoutFlag(d.flags, 'places') : clearPlaceFlags(d.flags, index);
      return { ...d, form: { ...d.form, places: next }, flags };
    });
    if (location.key !== 'default') navigate(-1);
    else navigate(FORM_PATH, { replace: true });
  };

  const editing = index !== null;
  return (
    <section data-testid="screen-3-3">
      <PageTitle
        title={editing ? `${index + 1}번 장소를\n고쳐 주세요` : '산책 동선에\n장소를 더해 주세요'}
        description="공개된 장소만 적어 주세요. 집이나 개인 공간은 빼 주세요."
      />
      <div className={styles.form}>
        <TextField
          label="장소 이름"
          value={place.name}
          maxLength={LIMITS.placeName}
          error={errors.name}
          onChange={(e) => setField('name', e.target.value)}
        />
        <TextField
          label="하고 싶었던 일"
          value={place.activity}
          maxLength={LIMITS.placeActivity}
          error={errors.activity}
          onChange={(e) => setField('activity', e.target.value)}
        />
        <TextArea
          label="이 장소를 고른 이유"
          rows={3}
          value={place.whyChosen}
          maxLength={LIMITS.placeWhy}
          error={errors.whyChosen}
          hint="선택 사항이에요."
          onChange={(e) => setField('whyChosen', e.target.value)}
        />
      </div>
      <PrimaryButton onClick={onSave}>{editing ? '저장하기' : '동선에 추가하기'}</PrimaryButton>
    </section>
  );
}
