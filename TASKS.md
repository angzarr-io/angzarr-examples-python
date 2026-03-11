# Tasks - angzarr-examples-python

## In Progress

## To Do

- [ ] Buf Proto Generation: Configure buf generate to fetch protos from buf.build/angzarr/angzarr
- [ ] Update Dependencies: Change angzarr-client from path dependency to PyPI package
- [ ] CI/CD Setup: Create .github/workflows/ci.yml for running behave tests
- [ ] Container Build: Update Containerfile to install angzarr-client from PyPI
- [ ] Feature File Sync: Add script to fetch features from angzarr core repo
- [ ] Deployment: Test skaffold deployment to Kind cluster

## Backlog

- [ ] Documentation: Add per-domain README files explaining business logic
- [ ] Integration Tests: Add tests against deployed cluster (ANGZARR_TEST_MODE=direct)

## Done

- [x] Initial extraction from angzarr core
- [x] Project structure with player/, table/, hand/ domains
- [x] Saga and process manager implementations
- [x] Projector implementations (output, cloud events)
