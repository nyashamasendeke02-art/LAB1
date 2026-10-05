import pytest

from autolab.worktrees import AgentIdentity, GitError, GitRepo, path_violations

ENG = AgentIdentity("claude-engineer", "e@x")


def test_isolated_worktrees_and_controlled_merge(tmp_path):
    repo = GitRepo.init(tmp_path / "repo")
    wt = repo.add_worktree(tmp_path / "wt" / "eng", "eng/T1-d0", "main")
    (wt / "a.py").write_text("x = 1\n")
    sha = repo.commit_all(wt, "impl", ENG, {"Autolab-Task": "TASK-1"})
    assert sha and not (repo.path / "a.py").exists()  # main untouched
    msg = repo.commit_message(sha)
    assert "Autolab-Task: TASK-1" in msg
    assert repo.git("log", "-1", "--format=%an", sha) == "claude-engineer"
    assert repo.changed_files(repo.rev("main"), sha) == ["a.py"]
    merged = repo.merge_into_main("eng/T1-d0", "merge", {"Autolab-Eng": "ENG-1"})
    assert (repo.path / "a.py").exists()
    assert len(repo.git("log", "-1", "--format=%P", merged).split()) == 2  # --no-ff
    repo.remove_worktree(wt)
    assert repo.branch_exists("eng/T1-d0")  # failed/old branches are kept


def test_commit_without_changes_returns_none(tmp_path):
    repo = GitRepo.init(tmp_path / "repo")
    wt = repo.add_worktree(tmp_path / "wt", "b", "main")
    assert repo.commit_all(wt, "nothing", ENG, {}) is None


def test_merge_refuses_dirty_main(tmp_path):
    repo = GitRepo.init(tmp_path / "repo")
    wt = repo.add_worktree(tmp_path / "wt", "b", "main")
    (wt / "f").write_text("1")
    repo.commit_all(wt, "f", ENG, {})
    (repo.path / "README.md").write_text("dirty")
    with pytest.raises(GitError):
        repo.merge_into_main("b", "m", {})


def test_merge_conflict_is_aborted(tmp_path):
    repo = GitRepo.init(tmp_path / "repo")
    wt = repo.add_worktree(tmp_path / "wt", "b", "main")
    (wt / "README.md").write_text("branch\n")
    repo.commit_all(wt, "b", ENG, {})
    (repo.path / "README.md").write_text("main\n")
    repo.commit_all(repo.path, "m", ENG, {})
    with pytest.raises(GitError):
        repo.merge_into_main("b", "m", {})
    assert repo.is_clean()


def test_path_policies():
    changed = ["experiment.py", "protocols/PROT-1.json", "tests/verification/test_v.py"]
    assert path_violations(changed, None, ["protocols/*", "tests/verification/*"]) == [
        "protocols/PROT-1.json", "tests/verification/test_v.py"]
    assert path_violations(changed, ["tests/verification/*"], []) == [
        "experiment.py", "protocols/PROT-1.json"]
