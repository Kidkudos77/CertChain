'use strict';

const { WorkloadModuleBase } = require('@hyperledger/caliper-core');

const FCCS_COURSES = ['CIS4385C', 'CIS4360', 'CIS4361', 'CNT4406', 'COP3710'];

// verifyCredential(credHash) needs a real, already-issued credHash to read.
// Caliper has no built-in "seed data then benchmark reads" primitive, so this
// module seeds a small pool of credentials itself during
// initializeWorkloadModule (before the timed round starts) and then cycles
// through that pool's credHashes for the actual measured verifyCredential
// calls.
class VerifyCredentialWorkload extends WorkloadModuleBase {
    constructor() {
        super();
        this.credHashes = [];
        this.callIndex = 0;
    }

    async initializeWorkloadModule(workerIndex, totalWorkers, roundIndex, roundArguments, sutAdapter, sutContext) {
        await super.initializeWorkloadModule(workerIndex, totalWorkers, roundIndex, roundArguments, sutAdapter, sutContext);

        const seedCount = (roundArguments && roundArguments.seedCount) || 5;
        for (let i = 0; i < seedCount; i++) {
            const studentID = `CALIPER-VERIFYSEED-${this.workerIndex}-${i}`;
            const nlpPayload = JSON.stringify({
                gpa: 3.5,
                courses_completed: FCCS_COURSES.slice(0, 3),
                bert_confidence: 0.9,
            });

            const result = await this.sutAdapter.sendRequests({
                contractId: 'certchain',
                contractFunction: 'issueMicroCredential',
                contractArguments: [studentID, nlpPayload],
                invokerIdentity: 'famu-institution',
                readOnly: false,
            });

            const payload = Array.isArray(result) ? result[0].GetResult().toString() : result.GetResult().toString();
            const parsed = JSON.parse(payload);
            if (parsed.success && parsed.credHash) {
                this.credHashes.push(parsed.credHash);
            }
        }

        if (this.credHashes.length === 0) {
            throw new Error('verifyCredential workload: failed to seed any credentials to verify.');
        }
    }

    async submitTransaction() {
        const credHash = this.credHashes[this.callIndex % this.credHashes.length];
        this.callIndex++;

        const request = {
            contractId: 'certchain',
            contractFunction: 'verifyCredential',
            contractArguments: [credHash],
            invokerIdentity: 'public-verifier',
            readOnly: true,
        };

        await this.sutAdapter.sendRequests(request);
    }
}

function createWorkloadModule() {
    return new VerifyCredentialWorkload();
}

module.exports.createWorkloadModule = createWorkloadModule;
