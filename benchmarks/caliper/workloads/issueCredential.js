'use strict';

const { WorkloadModuleBase } = require('@hyperledger/caliper-core');

// Mirrors the eligibility rules in chaincode/certchain.js so generated
// transactions exercise the real ELIGIBLE path (GPA >= 3.0, >=3 of the
// 5 FCCS course codes, bert_confidence high enough to clear THRESHOLD=0.70).
const FCCS_COURSES = ['CIS4385C', 'CIS4360', 'CIS4361', 'CNT4406', 'COP3710'];

class IssueCredentialWorkload extends WorkloadModuleBase {
    constructor() {
        super();
        this.txIndex = 0;
    }

    async submitTransaction() {
        this.txIndex++;
        const studentID = `CALIPER-${this.workerIndex}-${this.txIndex}`;
        const nlpPayload = JSON.stringify({
            gpa: 3.5,
            courses_completed: FCCS_COURSES.slice(0, 3),
            bert_confidence: 0.9,
        });

        const request = {
            contractId: 'certchain',
            contractFunction: 'issueMicroCredential',
            contractArguments: [studentID, nlpPayload],
            invokerIdentity: 'famu-institution',
            readOnly: false,
        };

        await this.sutAdapter.sendRequests(request);
    }
}

function createWorkloadModule() {
    return new IssueCredentialWorkload();
}

module.exports.createWorkloadModule = createWorkloadModule;
