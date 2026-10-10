import {QueryClient} from '@tanstack/react-query';
import {createRouter,rootRouteId} from '@tanstack/react-router';
import {describe,expect,it} from 'vitest';
import {routeTree} from '@/routeTree.gen';
describe('SafeHaven routing',()=>{it.each(['/','/map','/plan','/profile','/explore','/threat'])('matches %s',path=>{const router=createRouter({routeTree,context:{queryClient:new QueryClient()}});expect(router.matchRoutes(path).at(-1)?.routeId).not.toBe(rootRouteId)});});
