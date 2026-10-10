import {createFileRoute} from '@tanstack/react-router';
import {PlanScreen} from '@/components/safety-screens';
import {pageHead} from '@/lib/page-head';
export const Route=createFileRoute('/plan')({head:()=>pageHead('Your safety plan','Prepare emergency essentials with a calm step-by-step plan and go-bag checklist.'),component:PlanScreen});
