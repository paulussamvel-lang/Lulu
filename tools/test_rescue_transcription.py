import tempfile
import unittest
from pathlib import Path
import json
from rescue_transcription import activity_clips, align, assign, write


class RescueTests(unittest.TestCase):
    def test_activity_keeps_short_speech_and_skips_only_acoustic_gaps(self):
        turns=[dict(start=2,end=2.3),dict(start=3,end=5),dict(start=20,end=22)]
        self.assertEqual(activity_clips(turns,0,10),[1.5,5.5])
        self.assertEqual(activity_clips(turns,10,15),[])
        self.assertEqual(activity_clips(turns,20,21),[0,1])

    def test_actual_repetitions_survive_and_global_ids_do_not_reset(self):
        parts=[]
        for offset in [0,600]:
            parts.append(dict(offset=offset,result=dict(text='你好你好',segments=[dict(text='你好你好',start=1,end=3,words=[
                dict(word='你好',start=1,end=2),dict(word='你好',start=2,end=3)])])))
        turns=[dict(start=0,end=5,speaker_id=7),dict(start=600,end=605,speaker_id=7)]
        rows,fallback=align(parts,turns,610)
        self.assertEqual(''.join(r['text'] for r in rows),'你好你好你好你好')
        self.assertEqual([r['speaker_id'] for r in rows],[7,7])
        self.assertEqual([r['start'] for r in rows],[1,601])
        self.assertEqual(fallback,0)

    def test_overlap_is_unknown_instead_of_guessing(self):
        turns=[dict(start=0,end=3,speaker_id=1),dict(start=1,end=3,speaker_id=2)]
        self.assertIsNone(assign(1,2,turns))

    def test_missing_word_clock_preserves_original_segment(self):
        parts=[dict(offset=0,result=dict(text='重复重复',segments=[dict(text='重复重复',start=1,end=3,words=[])]))]
        rows,fallback=align(parts,[dict(start=0,end=4,speaker_id=1)],5)
        self.assertEqual(rows,[dict(start=1,end=3,speaker_id=1,text='重复重复')])
        self.assertEqual(fallback,1)

    def test_nonfinite_confidence_is_null_in_valid_json(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'checkpoint.json';write(p,dict(avg_logprob=float('nan'),text='保留保留'))
            self.assertEqual(json.loads(p.read_text()),dict(avg_logprob=None,text='保留保留'))


if __name__=='__main__':unittest.main()
