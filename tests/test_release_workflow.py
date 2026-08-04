from pathlib import Path


def test_release_workflow_uses_env_for_release_notes():
    workflow = Path(".github/workflows/release.yml").read_text()

    assert 'RELEASE_NOTES: ${{ steps.changelog.outputs.notes }}' in workflow
    assert '--notes "${RELEASE_NOTES}"' in workflow
    assert '--notes "${{ steps.changelog.outputs.notes }}"' not in workflow
