import os
import json
import sys
import time
import math
import re

def load_config(): 
    BASE_DIR = os.path.dirname(sys.argv[0])
    CONFIG_PATH = os.path.join(BASE_DIR, "finaloption", "config.json")

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = json.load(f)

    return config

def resolve_setup(passed_fusion):
    resolve_info = initialize_resolve(passed_fusion)
    resolve_info["voice_bin"] = check_voice_bin(resolve_info["root"],resolve_info["media_pool"])
    resolve_info["text_bin"] = check_text_bin(resolve_info["root"])

    return resolve_info

def initialize_resolve(passed_fusion): 
    if not passed_fusion:
        resolve = fusion.GetResolve() # type: ignore
        print ("直接実行")
    else:
        resolve = passed_fusion.GetResolve() #UIから呼び出しの可能性？
        print ("呼び出し実行")

    if not resolve:
        print("Resolve を取得できませんでした")
        return None

    project_manager = resolve.GetProjectManager()
    project = project_manager.GetCurrentProject()

    if not project:
        print("プロジェクトが開かれていません")
        return None

    timeline = project.GetTimelineByIndex(1)

    media_pool = project.GetMediaPool()
    root = media_pool.GetRootFolder()

    return {
        "timeline": timeline,
        "media_pool": media_pool,
        "root": root
    }

def make_incoming_files_info(config, resolve_info): 
    incoming_files_info = []
    add_count = 0
    existing_files_name = get_existing_names(resolve_info["voice_bin"])
    incoming_files_dir = scan_incoming_files(config["audio_folder"])
    for file in incoming_files_dir:
        #audio処理
        file_name, ext = os.path.splitext(file)

        if ext.lower() not in config["audio_ext"]:
            continue

        if file_name in existing_files_name:
            
            continue
        
        audio_path = os.path.join(config["audio_folder"], file)
        text_path = os.path.join(config["audio_folder"], file_name + ".txt")

        if os.path.exists(text_path):
            text_content = read_text_file(text_path)
            if not text_content:
                continue

            matched_character_key = match_character(config["track_map"], file_name, text_content)
            if not matched_character_key:
                continue

        else:
            print(f"同名txtファイルなし: {text_path}")
            continue

        audio_track = config["track_map"][matched_character_key]["audio"]
        video_track = config["track_map"][matched_character_key]["video"]
        check_track_count(resolve_info["timeline"], audio_track, video_track)

        #テキスト処理
        processed_text_content = process_text_content(text_content,config)

        incoming_files_info.append({
            "name": file_name,
            "audio_path": audio_path,
            "character" : matched_character_key,
            "text_content": processed_text_content,
            "audio_track": audio_track,
            "video_track": video_track
        })

        existing_files_name.add(incoming_files_info[-1]["name"])
        add_count += 1

    print(f"{add_count}個の新規ファイルを配置します")
    return incoming_files_info

def place_on_timeline(resolve_info,incoming_files_info):
    for current_file in incoming_files_info:
        current_frame = get_current_frame(resolve_info["timeline"])
        #audioクリップインポートと配置
        imported_audio_clip = import_audio_clip(resolve_info["media_pool"], current_file["audio_path"])
        if not imported_audio_clip:
            continue

        placed_audio_clip = place_audio_clip(resolve_info["media_pool"], current_file["audio_track"], imported_audio_clip, current_frame)
        if not placed_audio_clip:
            continue
        audio_record_frame = placed_audio_clip.GetStart()
        rounded_up_audio_duration = math.ceil(placed_audio_clip.GetDuration())
        print(f"音声配置: {current_file['name']} → A{current_file['audio_track']}")

        #Text+配置とFusion操作
        placed_textplus_clip = place_textplus_clip(resolve_info, current_file, audio_record_frame, rounded_up_audio_duration)
        if not placed_textplus_clip:
            continue

        fusion_comp_operation(placed_textplus_clip, current_file["text_content"])
        print(f"Text+配置 → V{current_file['video_track']}")

        link_clips(resolve_info["timeline"], placed_audio_clip, placed_textplus_clip)

def check_voice_bin(root,media_pool): 
    voice_bin = None
    for folder in root.GetSubFolderList():
        if folder.GetName().lower() == "voice":
            voice_bin = folder
            print("voiceビン確認完了")
            break

    if not voice_bin:
        voice_bin = media_pool.AddSubFolder(root, "voice")
        print("voiceビン作成完了")

    return voice_bin

def check_text_bin(root): 
    text_bin = None
    for folder in root.GetSubFolderList():
        if folder.GetName().lower() == "text":
            text_bin = folder
            print("Textビン確認完了")
            break

    if not text_bin:
        print("textビンが見つかりませんでした。text+が配置されているtextビンをマスタービン直下に作成してください")
        sys.exit()

    return text_bin

def get_existing_names(voice_bin): 
    existing_names = set()
    for clip in voice_bin.GetClipList():
        existing_names.add(clip.GetName().rsplit(".", 1)[0])

    return existing_names

def scan_incoming_files(folder): 
    incoming_files = []
    for i in range(3): # ファイル取得漏れを極力防ぐため、3回ファイルを取得する
        incoming_files = list(set(incoming_files + os.listdir(folder)))
        print(f"{i + 1}回目 ファイル数: {len(incoming_files)}")

        time.sleep(SLEEP_TIME)

    incoming_files = sorted(incoming_files)
    return incoming_files

def read_text_file(text_path):
    for enc in ["utf-8", "shift_jis"]:
        try:
            with open(text_path, "r", encoding=enc) as f:
                text_content = f.read()
            break

        except UnicodeDecodeError:
            continue
    else:
        print("文字コードが不明です")
        return None
    return text_content

def match_character(track_map,file_name,text_content): 
    matched_character_key = None
    for trackmap_character_key in track_map:
        if re.search(re.escape(trackmap_character_key), file_name):
            matched_character_key = trackmap_character_key
            break

        elif re.search(re.escape(trackmap_character_key), text_content):
            matched_character_key = trackmap_character_key
            break
    else:
        print(f"話者が特定できませんでした: {file_name}")
        return None

    return matched_character_key

def process_text_content(text_content,config): 
    replaced_text_content = replace_text_content(text_content,config["replacements"])
    wrapped_text_content = wrap_text_content(replaced_text_content,config["max_line_length"])

    return wrapped_text_content

def replace_text_content(text_content,replacements): 
    for replacement in replacements:
        text_content = re.sub(replacement["pattern"], replacement["replacement"], text_content)

    return text_content

def wrap_text_content(replaced_text_content,max_line_length): 
    wrapped_lines = []

    for i in range(0, len(replaced_text_content), max_line_length):
        wrapped_lines.append(
            replaced_text_content[i:i + max_line_length]
        )
    wrapped_text_content = "\n".join(wrapped_lines)

    return wrapped_text_content

def check_track_count(timeline, audio_track, video_track): 
    if timeline.GetTrackCount("audio") < int(audio_track):
        while timeline.GetTrackCount("audio") < int(audio_track):
            timeline.AddTrack("audio","mono")
        print(f"必要な音声トラック数が不足していたため、A{audio_track}まで追加しました")

    if timeline.GetTrackCount("video") < int(video_track):
        while timeline.GetTrackCount("video") < int(video_track):
            timeline.AddTrack("video")
        print(f"必要なビデオトラック数が不足していたため、V{video_track}まで追加しました")

def get_current_frame(timeline): 
    hh, mm, ss, ff = timeline.GetCurrentTimecode().split(":")
    fps = int(float(timeline.GetSetting("timelineFrameRate")))
    current_frame = (int(hh)*3600 + int(mm)*60 + int(ss)) * fps + int(ff)

    return current_frame

def import_audio_clip(media_pool, audio_path): 
    imported_audio_clip = media_pool.ImportMedia([audio_path])

    time.sleep(SLEEP_TIME)

    if not imported_audio_clip:
        print(f"インポート失敗: {audio_path}")
        return None
    else:
        return imported_audio_clip[0]

def place_audio_clip(media_pool,audio_track,imported_audio_clip, current_frame): 
    placed_audio_clip = media_pool.AppendToTimeline([{
        "mediaPoolItem": imported_audio_clip,
        "mediaType": 2,
        "trackIndex": audio_track,
        "recordFrame": current_frame,
    }])

    time.sleep(SLEEP_TIME)

    if not placed_audio_clip:
        print(f"配置失敗: {imported_audio_clip}")
        return None
    else:
        return placed_audio_clip[0]

def place_textplus_clip(resolve_info, current_file, audio_record_frame, rounded_up_audio_duration): 
    matched_textplus_clip = check_textplus_clip(resolve_info,current_file["character"])

    if not matched_textplus_clip:
        return None

    placed_textplus_clip = resolve_info["media_pool"].AppendToTimeline([{
        "mediaPoolItem": matched_textplus_clip,
        "startFrame": 0,
        "endFrame": rounded_up_audio_duration,
        "mediaType": 1,
        "trackIndex": current_file["video_track"],
        "recordFrame": audio_record_frame,
    }])

    time.sleep(SLEEP_TIME)

    if not placed_textplus_clip:
        print(f"Text+配置失敗: {current_file['name']}")
        return None
    else:
        return placed_textplus_clip[0]

def check_textplus_clip(resolve_info, character): 
    matched_textplus_clip = None
    textplus_clips = resolve_info["text_bin"].GetClipList()
    for tpclip in textplus_clips:
        if tpclip.GetClipProperty("Clip Name") == character:
            matched_textplus_clip = tpclip
            break
    if not matched_textplus_clip:
        print(f"一致するText+なし: {character}")
        return None
    else:
        return matched_textplus_clip

def fusion_comp_operation(placed_textplus_clip,text_content): 
    fusion_comp = placed_textplus_clip.GetFusionCompByIndex(1)
    if not fusion_comp:
        print("FusionCompなし")
        return None
    fusion_tools = fusion_comp.GetToolList()
    for fusion_tool in fusion_tools.values():
        fusion_tools_attrs = fusion_tool.GetAttrs()
        if fusion_tools_attrs["TOOLS_RegID"] == "TextPlus":
            fusion_tool.SetInput("StyledText", text_content)
            break
    return

def link_clips(timeline, audio_clip, textplus_clip): 
    timeline.SetClipsLinked([audio_clip, textplus_clip], True)
    time.sleep(SLEEP_TIME)

def main(passed_fusion=None):
    print("===== ふぁいなるおぷしょん動作開始 =====")
    config = load_config()

    global SLEEP_TIME
    SLEEP_TIME = config["sleep_time"]

    resolve_info = resolve_setup(passed_fusion)

    incoming_files_info = make_incoming_files_info(config, resolve_info)

    place_on_timeline(resolve_info, incoming_files_info)

    print("===== ふぁいなるおぷしょん動作完了 =====")

if __name__ == "__main__":
    main()
