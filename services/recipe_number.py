from sqlalchemy.orm import Session

from models import RecipeSequence


def generate_recipe_no(db: Session) -> str:
    """原子生成配方编号：A001→A999→B001→...→Z999→A0001→... 行锁防重"""
    seq = db.query(RecipeSequence).order_by(RecipeSequence.letter).with_for_update().first()
    if not seq:
        seq = RecipeSequence(letter="A", counter=0, digits=3)
        db.add(seq)
        db.flush()
    seq.counter += 1
    max_per_letter = 10 ** seq.digits - 1  # 3→999, 4→9999, 5→99999
    if seq.counter > max_per_letter:
        # 当前字母用完了，跳到下一个
        next_letter = chr(ord(seq.letter) + 1)
        if next_letter > "Z":
            # 所有字母用完，增加位数
            seq.digits += 1
            seq.letter = "A"
        else:
            seq.letter = next_letter
        seq.counter = 1
    db.flush()
    return f"{seq.letter}{seq.counter:0{seq.digits}d}"
