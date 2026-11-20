from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

root = Path.cwd()
logs = ['phase6_final.txt', 'phase6_final_resources.txt']
for name in logs:
    assert (root / '.test-tmp' / name).read_text(encoding='utf-8-sig').strip().endswith('OK'), name
with ZipFile(root / 'Exception_Genome_Phase_6.zip', 'w', ZIP_DEFLATED) as archive:
    for name in ('app.py', 'AGENTS.md', 'README.md', 'requirements.txt', 'Phase_4_Report.md',
                 'Phase_5_Report.md', 'Phase_6_Report.md', '.streamlit/config.toml', 'data/seed_services.json'):
        archive.write(root / name, name)
    for folder in ('core', 'ui', 'simulator', 'tests'):
        for file in sorted((root / folder).glob('*.py')):
            archive.write(file, file.relative_to(root))
    for name in logs:
        archive.write(root / '.test-tmp' / name, 'validation/' + name)
with ZipFile(root / 'Exception_Genome_Phase_6.zip') as archive:
    assert archive.testzip() is None
    print(len(archive.namelist()), 'verified archive members')

