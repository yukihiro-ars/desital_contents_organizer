
import os
import questionary
import glob
import shutil
from enum import Enum
from datetime import datetime
from tqdm import tqdm
from exif import Image

TARGET_EXT = ['mp4', 'mov', 'jpeg', 'jpg', 'png', 'gif']
HAS_EXIF_EXT = ['jpeg', 'jpg']
MSG_SELECT_PATH_1 = '整理対象のフォルダを選択してください'
MSG_SELECT_PATH_2 = 'フォルダ指定が不正です\nフォルダを再選択してください'
MSG_SHOW_PLAN = '整理計画を確認しますか？'
MSG_EXEC_PLAN = '整理計画を実行しますか？'
DATETIME_EXIF_KEY = ['datetime_original', 'datetime', 'datetime_digitized']


class PlaneMode(Enum):
    SHOW = 1
    EXEC = 2
    SAFE_EXEC = 3


# entry point
def do_organize():
    try:
        base_dir = None
        isFirst = True
        # ベースディレクトリ取得
        while base_dir is None or os.path.isdir(base_dir) is False:
            msg = MSG_SELECT_PATH_1 if isFirst else MSG_SELECT_PATH_2
            base_dir = questionary.text(msg).ask()
            print(base_dir)
            isFirst = False
            # TODO ずっとDir判定されない場合の救済処置は検討

        dict_ext = scan(base_dir)

        # TODO 全体に例外処理の見直しが必要
        # TODO base_dir末尾にスラッシュ指定された場合の対策検討
        # full path format
        def full_f(relative_path): return f'{base_dir}\\{relative_path}'

        dict_plan = planning(dict_ext, full_f)

        # 整理計画確認
        if questionary.confirm(MSG_SHOW_PLAN).ask():
            do_plan(PlaneMode.SHOW, dict_plan, full_f)

        # 整理計画実行
        if questionary.confirm(MSG_EXEC_PLAN).ask():
            do_plan(PlaneMode.EXEC, dict_plan, full_f)

        print('success.')
    except Exception as e:
        print(f'error. e={e}')
    finally:
        print('the process has completed.')


def scan(base_dir):
    '''
    ベースディレクトリスキャン
    拡張子単位で辞書型に分類
    '''
    # 指定フォルダ配下のファイル一覧を取得
    files = glob.glob('**/*.*', root_dir=base_dir, recursive=True)
    dict_ext = {}
    # 拡張子ごとに分類
    for file in files:
        # 拡張子取得(小文字統一)
        ext = file.rsplit('.', 1)[1].lower()
        # 拡張子ごとに分類
        if ext not in dict_ext:
            dict_ext[ext] = []
        dict_ext[ext].append(file)
    return dict_ext


def planning(dict_ext, full_f):
    '''
    dict_ext：スキャン結果の辞書
    full_f：絶対パス変換関数
    整理計画取得(年/年月/ファイル)
    '''
    dict_plan = {}
    for ext in dict_ext.keys():
        length = len(dict_ext[ext])
        # 対象拡張子に絞って処理続行
        if ext in TARGET_EXT:
            # TODO 余裕が出てきたらプログレスバーはtqdmをやめて自前で作ることも検討
            with tqdm(total=length, desc=ext) as pbar:
                for relative_path in dict_ext[ext]:
                    pbar.update(1)
                    dt = None
                    # https://gitlab.com/TNThieding/exif/-/issues/51
                    # TODO デコレータどっかで使えないかな
                    # https://qiita.com/mtb_beta/items/d257519b018b8cd0cc2e
                    full_path = full_f(relative_path)
                    # https://docs.python.org/ja/3/library/stat.html
                    file_stat = os.stat(full_path)
                    # 新名称フォーマット関数
                    def new_f(p_dt): \
                        return f'{p_dt}_{file_stat.st_size}.{ext}'
                    # exifの日付情報を取得(jpgのみ)
                    if ext in HAS_EXIF_EXT:
                        with open(full_path, 'rb') as file_stream:
                            image_desc = Image(file_stream)
                            if image_desc.has_exif:
                                dt = get_attr_if_exists_props(
                                    image_desc, DATETIME_EXIF_KEY)
                    # exifから日付情報が取得できない場合は、ファイルの更新日時より取得
                    if dt is None:
                        dt = file_stat.st_mtime
                    # 日付情報が取得できた場合
                    if dt is not None:
                        dt_dt = conv_datetime(dt)
                        try:
                            apply_file_part_by_file_new_old(
                                get_dict_dir_part_by_dt(dict_plan, dt_dt),
                                new_f(dt_dt.strftime('%Y%m%d_%H%M%S')),
                                relative_path)
                        except Exception as e:
                            raise Exception(
                                f'has error {full_path}.{e}')
                    else:
                        print(f'is datetime none {full_path}')
        else:
            # 対象外ファイルの退避処理
            print(f'no target ext = {ext}, len = {length}')
    return dict_plan


def conv_datetime(dt):
    '''
    dt：型不明の日付オブジェクト
    文字型、float型の場合にdatetime型に変換
    文字型の場合の期待形式：'%Y:%m:%d %H:%M:%S'
    float型の場合の期待値：エポックミリ秒
    '''
    if isinstance(dt, str):
        return datetime.strptime(dt, '%Y:%m:%d %H:%M:%S')
    elif isinstance(dt, float):
        return datetime.fromtimestamp(dt)
    else:
        raise Exception('Unexpected dt type. at conv_datetime')


def get_dict_dir_part_by_dt(dict_plan, dt_dt):
    '''
    dict_plan：辞書
    dt_dt：datetime型の日付オブジェクト
    辞書内に存在する対象日付の[%Y][%Y%m]で参照可能な要素を返却
    要素が存在しない場合、辞書内に当該要素を追加して返却
    '''
    try:
        ym = dt_dt.strftime('%Y%m')
        y = dt_dt.strftime('%Y')
        if y not in dict_plan:
            dict_plan[y] = {}
        if ym not in dict_plan[y]:
            dict_plan[y][ym] = {}
        return dict_plan[y][ym]
    except Exception as e:
        raise Exception(f'{e}. at get_dict_dir_part_by_dt')


def apply_file_part_by_file_new_old(dict_dir, new, old):
    '''
    dict_dir：ファイル格納する辞書要素
    new：新ファイル
    old：旧ファイル(元ファイル)
    同一のデータが別名で登録されていた場合
    旧ファイルは一つの新ファイルに対して複数紐づくことがある
    '''
    try:
        if new not in dict_dir:
            dict_dir[new] = []
        dict_dir[new].append(old)
    except Exception as e:
        raise Exception(f'{e}. apply_file_part_by_file_new_old')


def get_attr_if_exists_props(item, props):
    '''
    item：アイテム
    props：指定プロパティ（複数）
    アイテムに指定プロパティの中のいずれかが存在する場合、
    指定プロパティに紐づく値を返却
    '''
    try:
        for attr in props:
            if hasattr(item, attr):
                return getattr(item, attr)
        return None
    except Exception as e:
        raise Exception(f'{e}. get_attr_if_exists_props')


def do_plan(mode, dict_plan, full_f):
    '''
    mode:SHOW,EXEC
    dict_plan：整理計画
    full_f：絶対パス変換関数
    整理計画を表示
    '''
    # TODO セーフモード指定で対応できるようにするか(ファイルごとに実施する想定)？
    #   Backupフォルダに退避してから処理開始
    #   処理完了後、Backupフォルダのファイル削除
    # 関数判定 callable(func) = True
    # https://python-academia.com/file-transfer/
    # https://qiita.com/kuroitu/items/f18acf87269f4267e8c1#%E8%87%AA%E5%88%86%E3%81%A7%E4%BD%9C%E3%81%A3%E3%81%A6%E3%81%BF%E3%82%8B
    # 完了後Backupフォルダの対象ファイルを削除(ファイルごとに実施する想定)
    try:
        cnt = 0
        bk_cnt = 0
        for d1 in dict_plan.keys():
            if not os.path.isdir(full_f(d1)):
                # TODO dirさくせい
                print("test")
            for d2 in dict_plan[d1].keys():
                for new in dict_plan[d1][d2].keys():
                    cnt += 1
                    full_new = full_f(f'{d1}\\{d2}\\{new}')
                    olds = dict_plan[d1][d2][new]
                    full_old = full_f(olds[0])
                    isexist_new = os.path.isfile(full_old)
                    # リネーム
                    print(f'cp {full_old} => {full_new} , is exist old = {isexist_new}')
                    if mode == PlaneMode.EXEC:
                        shutil.move(src=full_old, dst=full_new)
                    # 重複データのバックアップ
                    if 1 < len(olds):
                        for old in olds:
                            if olds[0] != old:
                                bk_cnt += 1
                                full_bk_src = full_f(old)
                                full_bk_dst = full_f(f'{d1}\\{d2}\\bk\\{old}')
                                print(f'backup {full_bk_src} => {full_bk_dst}')
                                if mode == PlaneMode.EXEC:
                                    shutil.move(src=full_bk_src, dst=full_bk_dst)
        print(f'new count = {cnt}')
        print(f'bk count = {bk_cnt}')
        # TODO 終端処理 空のフォルダを削除
    except Exception as e:
        raise Exception(f'{e}. at do_plan')
