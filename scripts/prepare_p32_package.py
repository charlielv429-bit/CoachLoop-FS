"""Validate the supplied ZIP as data, convert candidates; never import/approve automatically."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
import zipfile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from pydantic import ValidationError
from integrations.reviewed_training.json_codec import decode
from integrations.curriculum_v3.registry import Archive
from integrations.curriculum_v3.candidates import convert, reported_evidence


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--zip',type=Path,required=True);parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args()
    with zipfile.ZipFile(args.zip) as package:
        names=('01_Expert_Reviewed_Answers.docx','02_Knowledge_Entries.docx','03_Knowledge_Candidates.json')
        if set(package.namelist())!=set(names) or any(i.file_size>2*1024*1024 for i in package.infolist()):
            parser.error('Unexpected or oversized package')
        artifacts={name:package.read(name) for name in names}
    raw=decode(artifacts[names[2]])
    try:Archive.model_validate(raw);initial_errors=[]
    except ValidationError as error:initial_errors=[{'loc':list(e['loc']),'type':e['type']} for e in error.errors()]
    archive=convert(raw)
    hashes={name:hashlib.sha256(data).hexdigest() for name,data in artifacts.items()}
    reports=reported_evidence(archive,hashes[names[2]],hashes[names[0]])
    report=dict(status='validated_candidates_not_approved',original_schema_error_count=len(initial_errors),original_schema_errors_by_type=dict(Counter(e['type'] for e in initial_errors)),original_schema_error_examples=initial_errors[:12],
        converted_schema='coachloop-kb-v3.0',entry_count=len(archive.entries),artifact_hashes=hashes,
        transformations={'claim':'content','version':'draft-0.1 retained as candidate_version; integer version=1',
                         'source_verification_status':'unverified mapped to pending, never verified'},
        missing=['教材原PDF/授权原文片段','逐条绑定的专项复核记录与审核人信息','大部分章节名与书籍版次'],
        locator_conflicts=[{'knowledge_id':k,'note':'候选条目B02定位PDF94–104；五问填答前压步为PDF90–93，保留原值，待原文逐页核对'} for k in ('K010','K011','K018')],
        professional_identity_created=False,system_approvals_created=0)
    args.output_dir.mkdir(parents=True,exist_ok=True)
    for name,value in [('p32-knowledge-import.json',archive.model_dump()),('p32-evidence-reports.json',{'reports':[r.model_dump() for r in reports]}),('p32-validation-report.json',report)]:
        path=args.output_dir/name
        with path.open('x',encoding='utf-8') as output:json.dump(value,output,ensure_ascii=False,indent=2)
    print('Validated candidates:',len(archive.entries),'; approvals: 0')

if __name__=='__main__':main()
