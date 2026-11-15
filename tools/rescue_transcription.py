"""Independent offline rescue: Whisper words + whole-recording diarization.

This does not import Lulu Core, alter its files, or impersonate a Lulu job.
Run each stage with the private request JSON produced for this one recording.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import math

os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
    HF_HUB_DISABLE_TELEMETRY='1', HF_HUB_DISABLE_IMPLICIT_TOKEN='1',
    TOKENIZERS_PARALLELISM='false', OMP_NUM_THREADS='4')


def write(path, value):
    def serializable(item):
        if isinstance(item,float) and not math.isfinite(item):return None
        if isinstance(item,dict):return {k:serializable(v) for k,v in item.items()}
        if isinstance(item,(list,tuple)):return [serializable(v) for v in item]
        return item
    path = Path(path)
    temp = path.with_name(path.name+'.tmp')
    with temp.open('w', encoding='utf-8') as f:
        os.chmod(temp, 0o600)
        json.dump(serializable(value), f, ensure_ascii=False, allow_nan=False)
        f.flush(); os.fsync(f.fileno())
    temp.replace(path)


def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(4*1024*1024), b''):h.update(block)
    return h.hexdigest()


def state(request, stage, **fields):
    value=dict(stage=stage, updated_at=time.time(), **fields)
    write(Path(request['output'])/(stage+'-status.json'), value)
    print(json.dumps(value,ensure_ascii=False),flush=True)


def prepare(request):
    import imageio_ffmpeg
    source=Path(request['source']);root=Path(request['output'])
    root.mkdir(parents=True,exist_ok=True,mode=0o700)
    assert digest(source)==request['source_sha256'], 'Source recording changed'
    wav=root/'audio16k.wav'
    if not wav.exists():
        subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-nostdin','-v','error','-i',str(source),
            '-vn','-ac','1','-ar','16000','-c:a','pcm_s16le',str(wav)],check=True)
        wav.chmod(0o600)
    import soundfile as sf
    info=sf.info(wav)
    assert info.samplerate==16000 and info.channels==1
    state(request,'prepare',completed=True,duration=info.duration,frames=info.frames)


def asr(request):
    import mlx_whisper
    import soundfile as sf
    root=Path(request['output']);parts=root/'asr-parts';parts.mkdir(exist_ok=True,mode=0o700)
    wav=root/'audio16k.wav';info=sf.info(wav);frames=info.frames;step=600*16000
    assert digest(Path(request['whisper_model'])/request.get('weights_file','weights.safetensors'))==request['whisper_sha256']
    options=dict(language='zh',task='transcribe',condition_on_previous_text=False,
        word_timestamps=True,temperature=0.,compression_ratio_threshold=None,
        no_speech_threshold=.6,logprob_threshold=-1.,hallucination_silence_threshold=None)
    if request.get('fp16') is False:options['fp16']=False
    if request.get('beam_size'):
        options['beam_size']=request['beam_size']
    activity=None
    if request.get('speech_turns'):
        activity=json.loads(Path(request['speech_turns']).read_text())
        assert activity['source_sha256']==request['source_sha256']
    for number,start in enumerate(range(0,frames,step)):
        target=parts/f'{number:03d}.json'
        if target.exists():
            old=json.loads(target.read_text());assert old['source_sha256']==request['source_sha256'] and old['options']==options
            continue
        state(request,'asr',part=number+1,total=(frames+step-1)//step,processed_seconds=start/16000)
        with sf.SoundFile(wav) as audio:
            audio.seek(start);samples=audio.read(min(step,frames-start),dtype='float32')
        clips=activity_clips(activity['turns'],start/16000,(start+len(samples))/16000) if activity else None
        if clips is not None and not clips:
            result=dict(text='',segments=[],language='zh',no_detected_speech=True)
        else:
            extra={'clip_timestamps':clips} if clips is not None else {}
            result=mlx_whisper.transcribe(samples,path_or_hf_repo=request['whisper_model'],verbose=False,**options,**extra)
        write(target,dict(source_sha256=request['source_sha256'],offset=start/16000,
            duration=len(samples)/16000,options=options,result=result))
        state(request,'asr',part=number+1,total=(frames+step-1)//step,
            processed_seconds=(start+len(samples))/16000,characters=len(result['text']))
    state(request,'asr',completed=True,processed_seconds=frames/16000)


def diarize(request, smoke=False):
    import sherpa_onnx
    import soundfile as sf
    root=Path(request['output']);models=Path(request['diarization_models'])
    for name,sha in request['diarization_hashes'].items():assert digest(models/name)==sha
    config=sherpa_onnx.OfflineSpeakerDiarizationConfig(
        segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
            pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(
                model=str(models/'sherpa-onnx-pyannote-segmentation-3-0/model.onnx'),window_shift_ratio=.1),
            num_threads=4,provider='cpu'),
        embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(
            model=str(models/'3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx'),num_threads=4,provider='cpu'),
        clustering=sherpa_onnx.FastClusteringConfig(
            num_clusters=(4 if smoke and not request.get('smoke_auto') else request.get('num_speakers',-1)),
            threshold=request.get('clustering_threshold',.5)),
        min_duration_on=.3,min_duration_off=.5)
    assert config.validate()
    pipeline=sherpa_onnx.OfflineSpeakerDiarization(config)
    source=models/'0-four-speakers-zh.wav' if smoke else root/'audio16k.wav'
    audio,sr=sf.read(source,dtype='float32');assert sr==pipeline.sample_rate and audio.ndim==1
    last=[-1]
    def progress(done,total):
        value=int(done/max(1,total)*100)
        if value//5>last[0]//5:
            state(request,'diarization',percent=value,done=done,total=total);last[0]=value
        return 0
    result=pipeline.process(audio,callback=progress).sort_by_start_time()
    remap={};turns=[]
    for segment in result:
        key=int(segment.speaker)
        if key not in remap:remap[key]=len(remap)+1
        a,b=float(segment.start),float(segment.end)
        assert 0<=a<b<=len(audio)/sr+.1
        turns.append(dict(start=a,end=b,speaker_id=remap[key]))
    if smoke:
        assert len(remap)==4
        state(request,'diarization-smoke',completed=True,speakers=4,turns=len(turns))
        return
    write(root/'speaker-turns.json',dict(source_sha256=request['source_sha256'],turns=turns,
        speaker_count=len(remap),scope='recording',clustering_threshold=request.get('clustering_threshold',.5)))
    state(request,'diarization',completed=True,speakers=len(remap),turns=len(turns))


def normalize(text):
    return ''.join(text.split())


def activity_clips(turns,start,end):
    """Conservative half-second acoustic padding; never deduplicate text."""
    intervals=[]
    for turn in turns:
        a,b=max(start,turn['start']-.5),min(end,turn['end']+.5)
        if a>=b:continue
        if intervals and a<=intervals[-1][1]+1.:
            intervals[-1][1]=max(intervals[-1][1],b)
        else:intervals.append([a,b])
    return [value-start for pair in intervals for value in pair]


def assign(start,end,turns):
    scores={}
    for turn in turns:
        if turn['end']<=start:continue
        if turn['start']>=end:break
        overlap=max(0.,min(end,turn['end'])-max(start,turn['start']))
        key=turn['speaker_id'];scores[key]=scores.get(key,0.)+overlap
    ordered=sorted(scores.items(),key=lambda pair:pair[1],reverse=True)
    if not ordered or ordered[0][1]<.5*(end-start):return None
    if len(ordered)>1 and ordered[1][1]>.35*(end-start):return None
    return ordered[0][0]


def align(parts,turns,duration):
    rows=[];all_text=[];fallback=0
    for part in parts:
        assert normalize(part['result']['text'])==normalize(''.join(s['text'] for s in part['result']['segments']))
        offset=part['offset']
        for segment in part['result']['segments']:
            text=segment['text']
            if not text.strip():continue
            all_text.append(text)
            words=segment.get('words',[])
            valid=(bool(words) and normalize(''.join(w['word'] for w in words))==normalize(text)
                and all(0<=offset+w['start']<offset+w['end']<=duration+.1 for w in words))
            units=words if valid else [dict(word=text,start=segment['start'],end=segment['end'])]
            if not valid:fallback+=1
            for word in units:
                a,b=offset+word['start'],offset+word['end']
                if not 0<=a<b<=duration+.1:
                    raise ValueError('Nonempty words have invalid clocks; preserved ASR checkpoints need review')
                speaker=assign(a,b,turns)
                if (rows and rows[-1]['speaker_id']==speaker and a-rows[-1]['end']<1.2
                        and b-rows[-1]['start']<20 and len(rows[-1]['text'])<120):
                    rows[-1]['text']+=word['word'];rows[-1]['end']=max(rows[-1]['end'],b)
                else:rows.append(dict(start=a,end=b,speaker_id=speaker,text=word['word']))
    assert normalize(''.join(all_text))==normalize(''.join(r['text'] for r in rows)), 'Words were lost or duplicated'
    return rows,fallback


def clock(seconds, srt=False):
    ms=round(seconds*1000);hours,ms=divmod(ms,3600000);minutes,ms=divmod(ms,60000);secs,ms=divmod(ms,1000)
    return f'{hours:02}:{minutes:02}:{secs:02}'+(',' if srt else '.')+f'{ms:03}'


def merge(request):
    import soundfile as sf
    root=Path(request['output']);duration=sf.info(root/'audio16k.wav').duration
    parts=[json.loads(p.read_text()) for p in sorted((root/'asr-parts').glob('*.json'))]
    cursor=0.
    for part in parts:
        assert abs(part['offset']-cursor)<.001 and part['source_sha256']==request['source_sha256']
        cursor+=part['duration']
    assert abs(cursor-duration)<.001, 'ASR did not cover the full recording'
    diar=json.loads((root/'speaker-turns.json').read_text());assert diar['source_sha256']==request['source_sha256']
    rows,fallback=align(parts,diar['turns'],duration)
    unknown=sum(r['speaker_id'] is None for r in rows)
    title=Path(request['source']).stem+' · 完整转录与整场分人'
    md=[f'# {title}','','> 本地识别；整场统一匿名编号。真实重复发言保留，重叠或声纹不足处标为待确认。','',
        f'总时长 {clock(duration)} · {diar["speaker_count"]} 个声纹组 · {unknown} 处待确认','','## 逐字稿','']
    subtitles=[]
    for n,row in enumerate(rows,1):
        speaker=f'发言人{row["speaker_id"]}' if row['speaker_id'] is not None else '发言人待确认'
        md.extend([f'**[{clock(row["start"])} — {clock(row["end"])}] {speaker}**',row['text'].strip(),''])
        subtitles.extend([str(n),f'{clock(row["start"],True)} --> {clock(row["end"],True)}',speaker+'：'+row['text'].strip(),''])
    payload=dict(source=request['source'],source_sha256=request['source_sha256'],duration=duration,
        engine=request.get('engine','mlx-whisper-large-v3-turbo'),speaker_pipeline='sherpa-onnx-pyannote-3dspeaker',
        diarization_scope='recording',speaker_count=diar['speaker_count'],unresolved_rows=unknown,
        segment_timestamp_fallbacks=fallback,segments=rows,words_preserved=True)
    write(root/'complete-transcript.json',payload)
    for name,text in [('完整转录与整场分人.md','\n'.join(md)),('完整转录与整场分人.srt','\n'.join(subtitles))]:
        p=root/name;p.write_text(text,encoding='utf-8');p.chmod(0o600)
    assert digest(request['source'])==request['source_sha256']
    state(request,'merge',completed=True,rows=len(rows),speaker_count=diar['speaker_count'],unresolved=unknown,
        words_preserved=True,duration=duration)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=['prepare','asr','diarize','smoke','merge']);parser.add_argument('request')
    args=parser.parse_args();request=json.loads(Path(args.request).read_text())
    if args.stage=='smoke':diarize(request,True)
    else:globals()[args.stage](request)
