import json
import unittest
from unittest.mock import Mock, patch
import requests
from multicloud_ai.core.models import NormalizedResource, Dependency
from multicloud_ai.core.planner import create_discovery_plan
from multicloud_ai.core.visualization import architecture_graph, graph_html, topology_summary
from multicloud_ai.core.agents import AgentClient, run_agent, redact
from multicloud_ai.core.terraform_runner import validate_cli, repair_terraform
from multicloud_ai.core.validation import validate_terraform_text
from multicloud_ai.core.quality import build_readiness_report
from multicloud_ai.core.terraform import generate


def final_response(terraform=''):
    answer = {'summary':'Evidence-based review', 'findings':['Observed resource'], 'next_steps':['Review'], 'terraform':terraform}
    return {'output':[{'type':'message','content':[{'type':'output_text','text':json.dumps(answer)}]}]}


def tool_response(name='read_evidence', args=None):
    return {'output':[{'type':'function_call','name':name,'call_id':'call1','arguments':json.dumps(args or {'section':'inventory','offset':0})}]}


class PhasePlanTests(unittest.TestCase):
    def setUp(self):
        self.vm=NormalizedResource('/subscriptions/s/resourceGroups/g/providers/Microsoft.Compute/virtualMachines/v','vm','Azure','compute_instance',region='eastus',configuration={'compute':{'vm_size':'Standard_B2s','os_type':'Linux'}})
        self.disk=NormalizedResource('disk','disk','Azure','block_storage',region='eastus',configuration={'storage':{'size_gb':30}})
        self.edge=Dependency(self.vm.resource_id,'disk','references','Explicit disk ID')

    def test_planner_deduplicates_azure_case_and_has_operations(self):
        alias=NormalizedResource(self.vm.resource_id.upper(),'vm','Azure','compute_instance')
        plan=create_discovery_plan([self.vm,alias], 'Azure')
        self.assertEqual(len(plan.resource_ids),1)
        self.assertEqual(plan.input_rows,2)
        self.assertEqual(plan.steps[0]['operation'],'ResourceGraph.resources')
        self.assertEqual(plan.plan_id,create_discovery_plan([alias,self.vm],'Azure').plan_id)

    def test_planner_skips_synthetic_ids(self):
        plan=create_discovery_plan([NormalizedResource('billing://aws/x','x','AWS','other')],'AWS')
        self.assertEqual(plan.resource_ids,[])
        self.assertTrue(plan.warnings)

    def test_gcp_ids_remain_case_sensitive(self):
        rows=[NormalizedResource(x,x,'GCP','other') for x in ['projects/p/A','projects/p/a']]
        self.assertEqual(len(create_discovery_plan(rows,'GCP').resource_ids),2)

    def test_graph_filter_and_export(self):
        graph=architecture_graph([self.vm,self.disk],[self.edge])
        self.assertEqual(graph.number_of_edges(),1)
        self.assertEqual(topology_summary(graph)['nodes'],2)
        filtered=architecture_graph([self.vm,self.disk],[self.edge],search='vm')
        self.assertEqual(filtered.number_of_edges(),0)
        html=graph_html(graph)
        self.assertIn('Download PNG',html)
        self.assertIn('vis.Network',html)

    def test_three_agents_use_tool_loop(self):
        for role in ['Scout','FinOps','Builder']:
            client=Mock(model='test-model')
            client.request.side_effect=[tool_response(),final_response()]
            result=run_agent(role,client,{'inventory':[{'name':'vm'}]})
            self.assertEqual(result['agent'],role)
            self.assertEqual(len(result['trace']),1)
            self.assertEqual(client.request.call_count,2)

    def test_agent_without_evidence_read_is_rejected(self):
        client=Mock(model='test',request=Mock(return_value=final_response()))
        with self.assertRaises(RuntimeError): run_agent('Scout',client,{'inventory':[]})

    def test_agent_unknown_tool_cannot_execute(self):
        client=Mock(model='test')
        client.request.side_effect=[tool_response('execute_shell'),final_response()]
        with self.assertRaises(RuntimeError): run_agent('Scout',client,{'inventory':[]})

    def test_agent_turn_budget(self):
        client=Mock(model='test',request=Mock(return_value=tool_response()))
        with self.assertRaises(RuntimeError): run_agent('Scout',client,{'inventory':[]},max_turns=2)
        self.assertEqual(client.request.call_count,2)

    def test_agent_timeout_and_key_not_in_error(self):
        client=AgentClient('secret-key','model',transport=Mock(side_effect=requests.Timeout('secret-key')))
        with self.assertRaises(RuntimeError) as error: client.request([],[])
        self.assertNotIn('secret-key',str(error.exception))

    def test_api_payload_does_not_store_responses(self):
        response=Mock(); response.json.return_value=final_response()
        transport=Mock(return_value=response)
        AgentClient('secret','model',transport=transport).request([],[])
        self.assertFalse(transport.call_args.kwargs['json']['store'])
        self.assertEqual(transport.call_args.args[0],'https://api.openai.com/v1/responses')

    def test_redaction(self):
        data=redact({'client_secret':'do-not-send','nested':[{'password':'abc'}]})
        self.assertNotIn('do-not-send',json.dumps(data))
        self.assertNotIn('abc',json.dumps(data))

    def test_cli_missing_is_not_success(self):
        with patch('multicloud_ai.core.terraform_runner.terraform_executable',return_value=None):
            self.assertEqual(validate_cli('resource "aws_s3_bucket" "x" {}','AWS')['status'],'not_run')

    def test_cli_blocks_executable_configuration(self):
        self.assertEqual(validate_cli('data "external" "x" { program = ["cmd"] }','AWS')['status'],'blocked')
        self.assertEqual(validate_cli('terraform { required_providers { x = { source = "attacker/tool" } } }','AWS')['status'],'blocked')

    def test_repair_revalidates_candidate(self):
        text='resource "aws_s3_bucket" "x" {}'
        with patch('multicloud_ai.core.terraform_runner.validate_cli',side_effect=[{'valid':False,'status':'failed'},{'valid':True,'status':'passed'}]) as validate, patch('multicloud_ai.core.agents.run_agent',return_value={'report':{'terraform':text}}):
            result=repair_terraform(text,'AWS',Mock(),{})
            self.assertTrue(result['validation']['valid'])
            self.assertEqual(validate.call_count,2)

    def test_repair_cannot_remove_resources(self):
        text='resource "aws_s3_bucket" "x" {}'
        with patch('multicloud_ai.core.terraform_runner.validate_cli',return_value={'valid':False,'status':'failed'}), patch('multicloud_ai.core.agents.run_agent',return_value={'report':{'terraform':'# removed'}}):
            result=repair_terraform(text,'AWS',Mock(),{})
            self.assertEqual(result['terraform'],text)
            self.assertIn('rejection',result['history'][0])

    def test_partial_pricing_cannot_get_high_readiness(self):
        report=build_readiness_report([self.vm],[self.vm],[self.edge],[{'Target Monthly Cost (USD)':1,'Pricing Reliability':'Partial'}],'resource "aws_instance" "x" {}\n# REVIEW REQUIRED: x\n# - detail')
        self.assertLessEqual(report.score,64)
        self.assertEqual(report.terraform_review_items,1)
        self.assertNotIn('High',report.grade)

    def test_all_target_syntax(self):
        for target in ['AWS','Azure','GCP']:
            text=generate([self.vm,self.disk],[],target)
            self.assertTrue(validate_terraform_text(text,target).valid, target)

    def test_invalid_hcl_rejected(self):
        self.assertFalse(validate_terraform_text('resource "aws_instance" "x" { x = }','AWS').valid)
