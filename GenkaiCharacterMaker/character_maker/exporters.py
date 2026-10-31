import re

LABELS = {'name': '名前', 'persona': '性格・価値観', 'appearance': '容姿',
          'speech_examples': '口調の例', 'background': '背景・過去', 'notes': '補足'}


def heading(text):
    text = text.replace('\r\n', ' ').replace('\r', ' ').replace('\n', ' ')
    text = text.replace('\\', '\\\\')
    text = re.sub(r'([`*_{}\[\]()#+.!|~\-])', r'\\\1', text)
    return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def markdown(doc):
    p = doc.character
    result = '# ' + heading(p.name or '未命名') + '\n'
    for key, label in LABELS.items():
        if key == 'name':
            continue
        value = getattr(p, key)
        if isinstance(value, list):
            value = '\n'.join('- ' + x.replace('\n', '\n  ') for x in value)
        result += f'\n## {label}\n\n{value}\n'
    if doc.custom_fields:
        result += '\n## 自由項目\n'
        for item in doc.custom_fields:
            result += f'\n### {heading(item.label)}\n\n{item.value}\n'
    return result


def novelwriter(doc):
    p = doc.character
    if not p.speech_examples:
        raise ValueError('5項目JSONの出力には口調の例が1件以上必要です')
    notes = p.notes
    if p.background:
        notes = '## 背景・過去\n' + p.background
        if p.notes:
            notes += '\n\n## 補足\n' + p.notes
    if doc.custom_fields:
        block = '## 自由項目\n\n' + '\n\n'.join(
            f'### {heading(f.label)}\n{f.value}' for f in doc.custom_fields)
        notes += ('\n\n' if notes else '') + block
    return {k: (notes if k == 'notes' else getattr(p, k))
            for k in ('name', 'persona', 'appearance', 'speech_examples', 'notes')}
